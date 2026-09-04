# Quality attributes — the numbers a design change is judged against

> One of the views indexed by [`ARCHITECTURE.md`](ARCHITECTURE.md).
> The *Forces* table there says what the architecture optimises for. This page
> says **how much**, so a change can fail one of those forces instead of merely
> disappointing it.

A force with no number cannot reject anything. "Write throughput" is a value;
"10,000 writes must cost ~100 statements, not 10,000" is a constraint. Every
figure below was measured, is dated, and carries the command that reproduces it.

**These are observations, not SLOs.** They are the current cost of the design,
recorded so a change that moves one by an order of magnitude is visible as a
decision rather than a surprise. Where a figure *is* load-bearing — the batching
ratio, the registry-per-database cost — the scenario says what would falsify it.

Each scenario is stated in the shape a quality-attribute scenario needs:
**stimulus** (what happens), **environment** (under what conditions),
**response** (what the system does), **measure** (the number that says whether
it did). One missing the environment is not reproducible; one missing the
measure is a wish.

## The measurement environment

Absolute values belong to one machine and one configuration. The *ratios* are
the portable part.

| | |
|---|---|
| Measured | **2026-08-08**, re-measured **2026-08-09**; Scenario 3 again and Scenarios 5–6 first on **2026-08-28** |
| CPU / RAM | Intel Core Ultra 9 185H, 22 logical cores, 30 GB |
| PostgreSQL | 18.4, unix-socket peer auth, local |
| Python | 3.14.4 (venv, with `odoo_rust` built in) |
| Server mode | `workers = 0` (threaded), `log_level = info`; Scenarios 5 and 6 are the exceptions and state their own — `workers = 4`, prefork |
| Databases | `base` only (154 models) and `sale_management,purchase,stock,account` (105 modules, 529 models); the 2026-08-09 latency repeat used `base,web`, also 154 models. The 2026-08-28 Scenario 3 repeat used the same two names, which by then held 19/162 and 114/597 — the drift is the point of stating them |

The four scenarios that existed then were all reproduced independently on
2026-08-09 against a
separately installed database; Scenario 3 was repeated again on 2026-08-28 and
Scenarios 5 and 6 were added that day. Where a repeat differs from the original it is
recorded in the scenario, with the environment that explains the difference.

Two registry sizes throughout, because one number would mislead: the framework's
costs scale with the *installed module set*, not with the framework, and a
`base`-only figure understates a real deployment by roughly the ratio between
the two columns.

## Scenario 1 — Write throughput

> **Stimulus** A loop assigns one field on each of 10,000 records.
> **Environment** One process, one transaction, no concurrent writers.
> **Response** Writes accumulate in the field cache; SQL is issued once, at
> flush, batched.
> **Measure** Statements issued, and the ratio to the un-batched equivalent.

| | Write statements | Wall |
|---|---:|---|
| **Deferred (the design)** | **100** | 1.454 s |
| Per-record flush (counterfactual) | 10,000 | 4.099 s |
| **Ratio** | **100 : 1** | 2.8 × |

**The loop issues no writes, not no statements.** Every write lands at flush;
reads do not. Re-measured 2026-08-09 on a `base`-only registry, the same loop
also issues prefetch `SELECT`s before the flush — 4 at N=2,000, 20 at N=10,000,
scaling with the number of prefetch batches rather than with the records. Count
writes, not statements: a regression that makes the loop issue *writes* is what
this scenario exists to catch, and the total buries it at 120 against 10,020
(84:1) where the write count is 100:1.

The batched form is not `WHERE id IN (…)` but a multi-row join:

```sql
UPDATE "res_partner"
   SET "comment" = "__tmp"."comment"::text, "write_date" = …, "write_uid" = …
  FROM (VALUES (%s, %s, %s, %s), …) AS "__tmp"
```

which is why 10,000 *different* values still collapse into 100 statements rather
than needing one per distinct value.

**What would falsify this:** any change that makes the loop issue SQL *writes* —
an implicit flush inside `write()`, a recompute that reads across the dirty set,
a constraint evaluated per record. The counterfactual row is what that regression
looks like, and it is 100× worse on statements before it is 3× worse on time, so
statement count is the earlier signal.

Reproduce: assign a field in a loop over 10k records with a counting wrapper on
`cr.execute`, flushing once at the end versus once per record, and count the
loop and the flush separately.

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

Building a registry costs **50× more** than loading one (35.85 s against
0.72 s): the cold path runs DDL and module data loading, the warm path only
composes classes and reads `ir_model*`. Anything that forces a rebuild — a
schema-affecting change, a module install — pays the upper number, which is why
registry invalidation is signalled rather than assumed.

Reproduce:

```bash
odoo-bin -c <conf> -d <db> -i <modules> --stop-after-init   # cold
odoo-bin -c <conf> -d <db> --stop-after-init                # warm
```

and read `Registry loaded in …s` from the log.

**Re-measured 2026-08-09**, same machine, same four modules, with ~20 other
sessions live on the box — so read the cold figures as an upper bound and the
warm ones as a clean repeat:

| | 2026-08-08 | 2026-08-09 |
|---|---|---|
| models installed by those 105 modules | 529 | **531** |
| Install + build, registry | 35.85 s | 42.92 s |
| Install peak RSS | 508 MB | 519 MB |
| Warm registry load | 0.72 s | 0.746 / 0.765 s |
| Warm boot, wall | 1.78 s | 1.82 / 1.84 s |
| Warm steady RSS | 224 MB | 228 MB |
| **cold ÷ warm** | **50×** | **58×** |

The warm column repeats to within a few percent; the cold one is ~20% slower
under load. **The ratio survived both**, which is the claim this scenario makes
and the reason the page says the ratios are the portable part.

The `base` column, three independent runs on 2026-08-09 (7.36 s / 8.15 s cold;
0.185–0.199 s warm across seven runs; 265–271 MB install peak; 164–170 MB warm
steady; 154 models each time) sits inside the same band. Cold ÷ warm for `base`
is 42×, below the 105-module figure: the ratio grows with the module set,
because the cold path's extra work is module data loading and DDL.

## Scenario 3 — Multi-tenancy cost

> **Stimulus** One process is asked to serve a second database.
> **Environment** Same process, both registries resident.
> **Response** A second, independent registry is built and held.
> **Measure** Resident memory added by the second registry.

| Second registry loaded | Added peak RSS | Condition |
|---|---|---|
| 154 models (`base`) | +8 MB | a *duplicate* schema — the same 154 models were already resident |
| 529 models (105 modules) | **+62 MB** | a schema not otherwise resident |

**Do not average these two.** They are 0.052 and 0.117 MB per model, and the
difference is the measurement condition, not a property of the registry: the
first loaded a second copy of a schema the process already held, so whatever the
framework interns across registries was already paid for. The **+62 MB for a
distinct 529-model registry is the figure to plan with**; the +8 MB says only
that duplicate tenants are cheaper than distinct ones, without saying how much
of that generalises.

**Re-measured 2026-08-28, and the condition turned out to be *overlap*, not
duplication.** The 2026-08-08 rows describe one order — `base` first, the larger
schema second. Running it both ways, three times each, on `base` (19 modules,
162 models today) and `sale_management,purchase,stock,account` (114 modules,
597 models — the same four names the 2026-08-08 row used, which have since
pulled in nine more modules and 68 more models):

| First registry | Second registry | Second adds | MB per model of the second |
|---|---|---:|---:|
| `base`, 162 models | 597 models | **+72.0 MB** | **0.120** |
| 597 models | `base`, 162 models | **+6.1 MB** | **0.037** |

The forward direction reproduces the row: 0.120 MB per model against 0.117 in
2026-08-08's +62 MB for 529, so the absolute moved with the model count and the
*rate* held to within 4 % across twenty days and 68 more models — which is what
this page means by the ratios being the portable part.

The reverse direction is the new result. `base`'s models are very nearly a
subset of the larger schema's, and loading it second costs **6 MB rather than
the 93 MB it costs first** — 0.037 MB per model against 0.57, a fifteenth of
the rate the same registry costs loaded into an empty process. So the second registry pays for **what the process
does not already hold**, not for its own size, and the +8 MB row is not a fact
about duplicate tenants: it is the same overlap effect at 100 %. A capacity
estimate built by multiplying tenants by a per-registry figure over-counts by
however much the tenants' schemas share.

First registries, for the same reason, are the expensive ones: 162 models cost
+92.6 MB loaded into an empty process (0.57 MB per model) and 597 cost
+160.2 MB (0.27), because the first registry pays every once-only cost the rest
inherit.

Method caveat: both are deltas of `ru_maxrss`, a *peak* that never falls. They
are lower bounds on growth and cannot observe memory being released.

The duplicate-schema row was first measured at +7 MB on 2026-08-08 and
reproduced twice since at +8 MB, loading two independently-installed `base`
databases into one process — 74/76 MB baseline, 165/167 after the first
registry, 173/175 after the second, the two registries distinct objects, which
is the property the row is about. The distinct-schema +62 MB has not been
re-measured: it needs the 105-module database resident beside another, and the
`ru_maxrss` caveat means a run on a loaded box would only inflate it.

**What would falsify this:** a shared, copy-on-write or interned representation
of field/model metadata across distinct registries would collapse the 62 MB; a
per-registry cache growing with *data* rather than schema would make it
unbounded. Neither is visible in a single measurement, which is why this
scenario states a condition rather than a rate.

Reproduce: install two databases, read
`resource.getrusage(RUSAGE_SELF).ru_maxrss` as a baseline, then in **one**
process construct `Registry(db)` for each in turn, reading the peak again after
each and asserting the two registry objects are distinct. Run it in both orders
— the pair is the measurement, not either number.

```bash
odoo-bin -c <conf> -d <db_a> -i base --stop-after-init
odoo-bin -c <conf> -d <db_b> -i sale_management,purchase,stock,account --stop-after-init
```

This block was missing until 2026-08-28. The page's closing rule — "A number
added to this page must arrive with its command and its date" — was stated and
half-enforced: a test read the date and nothing read the command, and the one
scenario that carried none was the one whose figure this page flagged as never
re-measured.

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
latency, is what a change to the request lifecycle moves.

The distributions are tight (p99 within 1.5× of p50 on both). That is the
threaded, single-process, no-contention case by construction; it says nothing
about `workers > 0` with real concurrency. Contention is the subject of
`retrying()`, and this page does not measure it.

**Reproduced 2026-08-09 on a 154-model registry** (`base,web`), same method,
loaded box — a registry 3.4× smaller than the row above:

| Route | p50 | p95 | p99 | max |
|---|---|---|---|---|
| `/web/health` | 2.0 ms | 2.4 ms | 3.6 ms | 7.1 ms |
| `/web/login` | 12.7 ms | 14.5 ms | 16.0 ms | 16.5 ms |
| **p50 difference** | **10.6 ms** | | | |

p50 matches to 0.1 ms on both routes and the difference reproduces exactly.
**Registry size does not drive request latency** — the per-request work does,
and 375 additional models moved neither route measurably. That is a stronger
result than the original row claimed and the reason to watch the difference
rather than the absolutes. The tails behave as the environment predicts: `max`
on the dispatch-only route is nearly 2× worse under load (7.1 ms against
3.8 ms), while p50 is unmoved.

Reproduce: install `base,web`, serve on a free port, then 200 requests per route
after a 30-request warm-up over one keep-alive connection, timing each
round-trip and reading percentiles off the sorted samples.

## Scenario 5 — Contention and retry

> **Stimulus** Sixteen clients write the same field on the **same record**,
> concurrently and without pause.
> **Environment** `PreforkServer`, `workers = 4`, `max_cron_threads = 0`,
> `db_maxconn = 24`, `base,web`, XML-RPC `res.partner.write` over loopback,
> 16 threads × 200 calls. Measured **2026-08-28**, two runs each way.
> **Response** PostgreSQL raises `SerializationFailure`; `retrying()` sleeps a
> uniform backoff and re-runs the handler, up to
> `MAX_TRIES_ON_CONCURRENCY_FAILURE`.
> **Measure** Throughput, latency percentiles, the retry rate, and how many
> requests exhaust the budget and reach the client as a 500.

The control is the same load on **sixteen different records**: identical
concurrency, identical request, only the row differs — so what separates the two
columns is contention and nothing else.

| | 16 rows (control) | 1 row (contended) |
|---|---|---|
| Throughput | 601.5 / 613.8 per s | **177.1 / 198.6 per s** |
| p50 | 26.3 / 25.5 ms | **67.1 / 61.3 ms** |
| p95 | 30.2 / 30.5 ms | 91.2 / 74.8 ms |
| p99 | 33.8 / 32.8 ms | **347.8 / 158.0 ms** |
| max | 165 / 186 ms | **2677 / 2028 ms** |
| Requests retried | **0** | 145 of 6,400 (2.3 %) |
| Failed to the client | **0 of 6,400** | **32 of 6,400 (0.5 %)** |

Contention on one row costs **~3× the throughput, ~2.5× the p50 and 5–10× the
p99**, and turns a run with no failures into one with a floor of half a percent.

**The retry ladder barely converges.** Every re-run logs one line, so the depth
distribution is countable without instrumenting anything. Across both contended
runs:

| Attempt | Requests still failing | Survived to here |
|---|---:|---:|
| 1st retry | 145 | — |
| 2nd | 97 | 67 % |
| 3rd | 69 | 71 % |
| 4th | 45 | 65 % |
| budget exhausted | **32** | 71 % |

Two thirds to three quarters of the requests that need one retry need another,
at **every** depth. So **22 % of the requests that ever retried failed
outright** — the ladder sheds about a third of its survivors per rung, and five
rungs is not enough to drain a queue that is being refilled.

**`retrying()` is a burst absorber, not a queue.** `delay()` draws
`uniform(0, ceiling)` with the ceiling doubling from
`BASE_CONCURRENCY_BACKOFF_SECONDS` to `MAX_CONCURRENCY_BACKOFF_SECONDS`, which
spreads a *burst* of writers apart. Under a load that never stops offering, a
retry lands back into the same contention it left, and the mechanism converges
to a fixed loss rate instead of to zero. That is the shape to design against:
retry budgets protect against transient conflict, and no budget converts
sustained same-row write contention into success.

**What would falsify this:** a workload where the retried requests drain — where
the per-rung survival falls sharply rather than staying near 70 % — would mean
the backoff is doing what it looks like it does. A *lower* failure rate at
higher concurrency would mean the loss is queueing, not serialization; it is
not, since the control at the same concurrency loses nothing.

Reproduce: boot prefork on a free port, create enough records for the control,
then drive N client threads through XML-RPC `execute_kw(..., "res.partner",
"write", ...)` — all on one id for the contended column, one id each for the
control — timing every round trip, and count the server's retry lines.

```bash
odoo-bin -c <conf> -d <db> --http-port 8171 --workers 4 \
    --max-cron-threads 0 --db_maxconn 24
grep -c "tries left, try again" <server log>          # retries
grep -c "maximum number of tries reached" <server log>  # budget exhausted
```

## Scenario 6 — Cross-process invalidation

> **Stimulus** One worker clears a named cache — `ir.config_parameter.set_param`
> calls `registry.clear_cache("stable")`, which `INSERT`s a row into
> `orm_signaling_stable` and keeps the id the database generated.
> **Environment** `PreforkServer`, `workers = 4`, `max_cron_threads = 0`,
> `base,web`, loopback, measured **2026-08-28**. Two conditions: eight client
> threads keeping every worker busy, and no traffic at all.
> **Response** Every other worker reads the sequence on its next
> `check_signaling()` and drops the LRUs behind that key, logging one line.
> **Measure** How long that takes, and how many of the other workers it reaches.

| | 8 background clients | no traffic |
|---|---|---|
| Other workers reached per signal | **3 of 3**, on 9 of 10 rounds | **none** |
| p50 | **1 ms** | — |
| p95 / max | 3 ms / 3 ms | — |

**The latency is not the interesting half; the placement is.**
`check_signaling()` is called from `_acquire_registry_cursor`
(`odoo/http/_serve.py`), on the read-only cursor the request was already
taking, **before the request is dispatched**. So it is a poll at request start,
not a push — which is why the idle column is empty, and why that is correct
rather than a defect: a worker serving nothing has no opportunity to serve a
stale cache, and the first request it does take clears the cache before
dispatch. Staleness is bounded by "before the next request", not by a
propagation delay.

Two consequences worth carrying:

**The tax is one query, not eight.** `get_sequences` builds a single `SELECT`
of eight scalar subqueries, one per signalling table, so the per-request cost of
the whole mechanism is one round trip — **1.08 ms measured from `psql`**, and
less in-process, on a cursor already being acquired. A design that polled each
table separately would pay eight.

**A quoted propagation figure belongs to a traffic level.** The 1 ms above is
what a *busy* worker shows. The same signal reaches an idle worker in no time at
all, because nothing is looking; a deployment with uneven traffic has workers
whose caches are arbitrarily old and none of them can serve one.

**What would falsify this:** a worker dispatching a request on a registry older
than the sequence in the database — which would mean the check has moved off the
cursor-acquisition path, or that the read-only cursor is landing on a replica
far enough behind to report no change. The second is not hypothetical and is
described in [`data.md`](data.md#2-the-signalling-tables--cross-process-coordination):
signalling read through a replica reads *below* the local sequence as staleness
and ignores it, but a replica merely behind reads as "nothing has changed".

Reproduce: boot prefork on a free port, keep N clients calling any cheap route
so every worker is serving, then call `set_param` from one more client and read
the deltas out of the server's own log — the access line for the signalling
request and the `Invalidating caches after database signaling` line each worker
writes. Both carry the pid, so no clock alignment with the client is needed.

```bash
odoo-bin -c <conf> -d <db> --http-port 8172 --workers 4 --max-cron-threads 0
grep "Invalidating caches after database signaling" <server log>
```

## What this page does not measure

- **Contention on anything but one row.** Scenario 5's two columns are the
  extremes: total conflict and none. Realistic workloads sit between, and where
  the retry ladder starts converging is not measured.
- **Flush fixpoint depth.** How many passes a realistic write takes is
  unmeasured, and non-convergence is an error the architecture asserts but this
  page does not characterise.
- **Cold filestore and large attachments.** No I/O-bound scenario appears here.
- **Upgrade of a populated database.** Scenario 2's cold path installs into an
  empty database; migrating one with data is a different, larger cost.

A number added to this page must arrive with its command and its date, in the
same form as the rest — a measurement whose environment is not stated is not
reproducible, and one that is not dated will be read as current forever.
