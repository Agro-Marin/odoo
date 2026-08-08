# Quality attributes — the numbers a design change is judged against

> One of the views indexed by [`odoo/ARCHITECTURE.md`](../../odoo/ARCHITECTURE.md).
> The *Forces* table there says what the architecture optimises for. This page
> says **how much**, so a change can fail one of those forces instead of merely
> disappointing it.

A force with no number cannot reject anything. "Write throughput" is a value;
"10,000 writes must cost ~100 statements, not 10,000" is a constraint, and the
difference is whether a reviewer can say no with evidence. Every figure below
was measured, is dated, and carries the command that reproduces it.

**These are observations, not SLOs.** Nothing here is a promise to a user; they
are the current cost of the design, recorded so that a change which moves one by
an order of magnitude is visible as a decision rather than a surprise. Where a
figure *is* load-bearing — the batching ratio, the registry-per-database cost —
the scenario says what would falsify it.

## How to read a scenario

Each is stated in the shape a quality-attribute scenario needs to be actionable:
**stimulus** (what happens), **environment** (under what conditions),
**response** (what the system does), **measure** (the number that says whether
it did). A scenario missing the environment is not reproducible, and one missing
the measure is a wish.

## The measurement environment

Every number on this page comes from one machine and one configuration. Moving
either invalidates the absolute values; the *ratios* are the portable part.

| | |
|---|---|
| Measured | **2026-08-08** |
| CPU / RAM | Intel Core Ultra 9 185H, 22 logical cores, 30 GB |
| PostgreSQL | 18.4, unix-socket peer auth, local |
| Python | 3.14.4 (venv, with `odoo_rust` built in) |
| Server mode | `workers = 0` (threaded), `log_level = info` |
| Databases | `base` only (154 models) and `sale_management,purchase,stock,account` (105 modules, 529 models) |

Two registry sizes are measured throughout because one number would mislead:
the framework's costs scale with the *installed module set*, not with the
framework, and a `base`-only figure understates a real deployment by roughly the
ratio between the two columns.

## Scenario 1 — Write throughput

> **Stimulus** A loop assigns one field on each of 10,000 records.
> **Environment** One process, one transaction, 529-model registry, no
> concurrent writers.
> **Response** Writes accumulate in the field cache; SQL is issued once, at
> flush, batched.
> **Measure** Statements issued, and the ratio to the un-batched equivalent.

| | Statements | Wall |
|---|---|---|
| **Deferred (the design)** | **100** | 1.454 s |
| Per-record flush (counterfactual) | 10,000 | 4.099 s |
| **Ratio** | **100 : 1** | 2.8 × |

During the loop itself the cursor issues **zero** statements — the entire cost
lands at flush. The batched form is not `WHERE id IN (…)` but a multi-row join:

```sql
UPDATE "res_partner"
   SET "comment" = "__tmp"."comment"::text, "write_date" = …, "write_uid" = …
  FROM (VALUES (%s, %s, %s, %s), …) AS "__tmp"
```

which is why 10,000 *different* values still collapse into 100 statements rather
than needing one per distinct value. **What would falsify this:** any change
that makes the loop issue SQL — an implicit flush inside `write()`, a recompute
that reads across the dirty set, a constraint evaluated per record. The
counterfactual row is what that regression looks like, and it is 100× worse on
statements before it is 3× worse on time, so statement count is the earlier
signal.

Reproduce: assign a field in a loop over 10k records with a counting wrapper on
`cr.execute`, flushing once at the end versus once per record.

## Scenario 2 — Registry build and boot

> **Stimulus** A process starts and must serve a database.
> **Environment** Cold (schema created, modules installed) versus warm (registry
> assembled from an installed database).
> **Response** The module graph is loaded and the runtime model classes are
> composed.
> **Measure** Registry build time, process wall time, peak RSS.

| | `base` (154 models) | 105 modules (529 models) |
|---|---|---|
| Install + build, registry | 7.16 s | **35.85 s** |
| Install + build, wall | 8.35 s | 37.53 s |
| Install peak RSS | 262 MB | 508 MB |
| **Warm registry load** | 0.187 s | **0.72 s** |
| Warm boot, wall | 1.06 s | 1.78 s |
| Warm steady RSS | 164 MB | 224 MB |

The gap between the two rightmost figures is the architectural point: building a
registry costs **50× more** than loading one (35.85 s against 0.72 s), because
the cold path runs DDL and module data loading while the warm path only composes
classes and reads `ir_model*`. Anything that forces a rebuild — a schema-affecting
change, a module install — pays the upper number, which is why registry
invalidation is signalled rather than assumed (see
[*Cross-process invalidation*](../../odoo/ARCHITECTURE.md)).

Reproduce:

```bash
odoo-bin -c <conf> -d <db> -i <modules> --stop-after-init   # cold
odoo-bin -c <conf> -d <db> --stop-after-init                # warm
```

and read `Registry loaded in …s` from the log.

## Scenario 3 — Multi-tenancy cost

> **Stimulus** One process is asked to serve a second database.
> **Environment** Same process, both registries resident.
> **Response** A second, independent registry is built and held.
> **Measure** Resident memory added by the second registry.

| Second registry loaded | Added peak RSS | Condition |
|---|---|---|
| 154 models (`base`) | +7 MB | a *duplicate* schema — the same 154 models were already resident |
| 529 models (105 modules) | **+62 MB** | a schema not otherwise resident |

**Do not average these two.** They are 0.045 and 0.117 MB per model
respectively, and the difference is the measurement condition, not a property of
the registry: the first loaded a second copy of a schema the process already
held, so whatever the framework interns across registries was already paid for.
The **+62 MB for a distinct 529-model registry is the figure to plan with**; the
+7 MB says only that duplicate tenants are cheaper than distinct ones, without
saying how much of that generalises.

Method caveat: both are deltas of `ru_maxrss`, which is a *peak* and never
falls. They are therefore lower bounds on growth and cannot be used to observe
memory being released.

**What would falsify this:** a shared, copy-on-write or interned representation
of field/model metadata across distinct registries would collapse the 62 MB; a
per-registry cache that grows with *data* rather than schema would make it
unbounded. Neither is visible in a single measurement, which is why this
scenario states a condition rather than a rate.

## Scenario 4 — Request latency

> **Stimulus** An unauthenticated HTTP request arrives.
> **Environment** Threaded server (`workers = 0`), warm registry (529 models),
> loopback client, 200 requests after a warm-up.
> **Response** The request is dispatched; a full route additionally opens a
> transaction, queries, and renders.
> **Measure** Latency percentiles.

| Route | p50 | p95 | p99 | max |
|---|---|---|---|---|
| `/web/health` (dispatch only) | 2.0 ms | 2.7 ms | 3.6 ms | 3.8 ms |
| `/web/login` (transaction + ORM + QWeb) | 12.6 ms | 13.9 ms | 15.2 ms | 18.7 ms |

The **~10.6 ms difference at p50 is the cost of everything the framework adds
over bare HTTP dispatch** — cursor acquisition, environment construction, the
ORM reads behind the template, and rendering. That figure, not the absolute
latency, is the one to watch: it is what a change to the request lifecycle moves.

Note the distributions are tight (p99 within 1.5× of p50 on both). That is the
threaded, single-process, no-contention case by construction — it says nothing
about behaviour under `workers > 0` with real concurrency, and must not be read
as though it did. Contention is the subject of `retrying()`, and this page does
not yet measure it.

## What this page does not measure

Named so the gaps are visible rather than implied:

- **Contention and retry.** `retrying()` re-runs a handler on serialization and
  deadlock errors; the rate at which that happens under real concurrency, and
  the cost of a re-run, are unmeasured. This is the most load-bearing gap.
- **`workers > 0`.** Every figure here is threaded, single-process. The
  cross-process signalling path is therefore exercised by none of them.
- **Flush fixpoint depth.** Recomputation can dirty further fields; how many
  passes a realistic write takes is unmeasured, and non-convergence is an error
  the architecture asserts but this page does not characterise.
- **Cold filestore and large attachments.** No I/O-bound scenario appears here.
- **Upgrade of a populated database.** Scenario 2's cold path installs into an
  empty database; migrating one with data is a different, larger cost.

A number added to this page must arrive with its command and its date, in the
same form as the rest — a measurement whose environment is not stated is not
reproducible, and one that is not dated will be read as current forever.
