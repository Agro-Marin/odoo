# Odoo Framework Core — Architecture

The framework core in `odoo/` — ORM, persistence, HTTP, server, module system,
utilities. This page is the front door: what the core is *for*, the forces that
shaped it, the mechanisms that cut across every part of it, and an index of the
views that describe it in detail. It is the framework-level counterpart to the
per-addon `machine_doc_v1/ARCHITECTURE.md` maps.

| If you are… | Read |
|---|---|
| new to the core | *Context* and *The forces* below, then [`views/module.md`](../doc/architecture/views/module.md) |
| placing new code | *Where to add code* below |
| debugging a runtime path | [`views/runtime.md`](../doc/architecture/views/runtime.md) |
| changing a boundary | [`gates.md`](../doc/architecture/gates.md), then `doc/adr/` |
| wondering why a rule exists | `doc/adr/`, then [`MEASUREMENTS.md`](../doc/architecture/MEASUREMENTS.md) |
| judging a change's cost | [`qualities.md`](../doc/architecture/qualities.md) |

## Context

The core is not an application. It is the machine that turns a set of installed
*addons* into a running, multi-tenant, database-backed web application, and
almost every design decision below follows from that sentence.

```
      browser (OWL client)          odoo-bin CLI            cron / queue
             │  HTTP/JSON-RPC             │                      │
             ▼                            ▼                      ▼
   ┌───────────────────────────────────────────────────────────────────┐
   │  FRAMEWORK CORE  (odoo/)                                          │
   │    http/  serving · routing · sessions                            │
   │    service/  process lifecycle · the servers · cron · retrying()   │
   │    orm/  models · fields · domains · Environment/Registry/Txn      │
   │    modules/  the module graph and what loads it                   │
   │    db/  pool · cursors · DDL · resilience                         │
   └───────────────────────────────────────────────────────────────────┘
        │                    │                      │
        ▼                    ▼                      ▼
   PostgreSQL          filestore              addons on disk
   (N databases,       (attachment            (odoo/addons/, addons/,
    one registry        bytes)                 enterprise/, agromarin/…)
    each)                                      = the extension surface
```

Four properties of that picture do more to explain the core than any module
boundary:

- **Addons are the product.** The framework ships almost no business behaviour;
  it ships the machinery that lets hundreds of independently-authored modules
  extend each other's models, views and routes. Extension is not a feature of
  this system, it is the system.
- **One process serves many databases**, each with its own registry, schema and
  installed-module set. Nothing may be cached per-process without being keyed by,
  or invalidated per, database.
- **One deployment runs many processes** that share no memory (`workers > 0`).
  Every piece of cross-process coordination therefore goes through PostgreSQL.
- **The schema is data.** Models, fields and views exist as rows in `ir_model*`
  as well as Python objects, and installing a module mutates the database schema
  at run time. There is no build step that freezes the shape of anything.

## The forces

What the architecture optimises for, stated so it can be argued with. These are
the drivers behind the layering, the seams and the mechanisms; a design change
that makes one of them worse needs a reason.

| Force | What it demands | Where it shows up |
|---|---|---|
| **Third-party extensibility** | a module must add fields, override methods and inherit views on a model it does not own, without patching it | `_inherit` registry assembly; the `odoo.api`/`fields`/`models` façades; string-keyed model lookup |
| **Upgrade safety** | an installed database must survive its addons changing shape | `Registry.new()` phases; `ir_model*` as a meta-schema; the migration hooks in `modules/` |
| **Multi-tenancy** | N databases per process, isolated | registry per database; `check_signaling` keyed per DB |
| **Horizontal scale** | N processes with no shared memory | database-mediated registry/cache signaling |
| **Write throughput** | a loop that touches 10k records must not issue 10k `UPDATE`s | deferred writes; the flush fixpoint loop; `cr.pipeline()` |
| **Correctness under contention** | concurrent requests must not corrupt or silently lose writes | `retrying()` on serialization/deadlock; savepoints; the RO→RW promotion |
| **Testability without a database** | the hardest logic must be exercisable in milliseconds | `orm/components/` as pure Python; `InMemoryBackend` (ADR-0011) |
| **A refactorable core** | internal layout must move without breaking hundreds of addons | the façade boundary (ADR-0008) and the layer contracts (ADR-0001, ADR-0005) |

The last one is this fork's own addition and the reason `tooling/architecture/`
exists at all. Upstream treats the core's internal shape as fixed; `19.0-marin`
treats it as the thing most worth improving, which is only safe if the public
surface is mechanically pinned.

## Non-goals

What this architecture deliberately does **not** try to be. These are as
load-bearing as the forces: each one buys something above, and an argument that
appeals to one of them has already been settled.

| Non-goal | Why, and what it buys |
|---|---|
| **Merge-compatibility with upstream Odoo** | `19.0-marin` carries no backward-compatibility obligation to upstream and never merges from `19.0` (*Scope and precedence*, `doc/coding_guidelines.rst`). "It complicates the upstream merge" is not a cost this fork pays, which is what makes core refactoring affordable at all. |
| **Stability of core internals** | The *façade* is the public surface — `odoo.api` / `odoo.fields` / `odoo.models`, each with an explicit `__all__` (ADR-0008). Everything behind it is free to move, which is the whole point of pinning the front (ADR-0001, ADR-0005) rather than freezing the inside. |
| **Business behaviour in the core** | The framework ships the machinery for addons to extend each other, and almost no domain logic. Behaviour that belongs to a business process belongs in an addon. |
| **A build step that freezes shape** | Models, fields and views are rows as well as Python objects, and installing a module mutates the schema at run time. Nothing is resolved at import time because the contributor set is not known until the module graph is loaded. |
| **Database-driver portability** | psycopg 3 only — `odoo/db/` imports `psycopg` exclusively and psycopg2 is not installed, so a stray import fails loudly instead of compiling a branch that can never run. |

## Mechanisms

Five stories that cut across every view. A newcomer who holds these can read the
rest; the views give the detail, and each links back here.

### Models are assembled per database, not defined

A model class in the tree is a *definition*, not the class you get at run time.
`orm/registration.py::add_to_registry` composes the runtime class for a database
by multiple inheritance over every installed module's contribution to that
`_name` — `_inherit` collects parents, `_inherits` sets up delegation, and
`setup_model_classes(env)` then resolves fields across the whole graph. So
`env["res.partner"]` in one database is a genuinely different class from the same
name in another, because a different set of modules built it.

Everything awkward about the ORM follows from this. Fields cannot be resolved at
import time, because the set of contributors is not known until the module graph
is loaded. The framework cannot import addon-owned models, because they may not
exist — hence `env["res.users"]` by string key, its own gate
(`env_model_surface_check.py`), and the fact that the framework's largest real
coupling to its consumer produces no import edge at all.

### Writes do not reach SQL where you write them

`create()`/`write()` update the field cache, mark ids dirty and schedule
dependent recomputes; the database sees nothing until a flush. A flush is a
*fixpoint loop*, because recomputing one field can dirty another, and
non-convergence is an error rather than a warning. This is what buys write
throughput, and it is also why "the value I just wrote isn't in the database yet"
is normal rather than a bug. Detail: [*Transaction, cache and
flush*](../doc/architecture/views/runtime.md#transaction-cache-and-flush).

### Cross-process invalidation runs through PostgreSQL

Because `workers > 0` means processes that share no memory, a registry change in
one worker is published by `INSERT`ing into a signaling table and taking back the
id the database generated; every other worker notices on its next
`check_signaling()` and either rebuilds its registry or clears the named caches.
This is the mechanism that makes the process model architectural rather than a
deployment knob, and it is why any process-lifetime cache must be registered in
`CACHES_BY_KEY`. Detail: [*Concurrency, and why the process model is
architectural*](../doc/architecture/views/runtime.md#concurrency-and-why-the-process-model-is-architectural).

### Access control is a model-layer concern, applied per operation

Every model carries `AccessMixin` (`orm/models/mixins/access.py`), so the checks
are methods on the recordset rather than a separate enforcement layer: two tiers
— model-level permissions per CRUD operation, and record-level rules that
contribute a domain — plus field-level (`_has_field_access`,
`check_field_access_rights`) and multi-company (`_check_company`) checks.
`_check_access(operation)` hands back the accessible subset together with the
callable that explains the refusal, which is what lets a caller either filter or
raise from one code path.

Superuser is not a bypass flag threaded through call sites: `sudo()` returns an
environment whose `su` is part of the `(cr, uid, su, context)` interning key, so
privilege is a property of the environment a recordset carries, and two
recordsets that differ only in privilege are different objects by construction.

### A request is a transaction, and it may run twice

`retrying()` (in `service/transaction.py`, not on a model) re-runs the handler on
PostgreSQL serialization and deadlock errors, and a `readonly` route that turns
out to write is re-run on a read/write cursor. Handlers must therefore be safe to
execute more than once: non-transactional side effects — mail, outbound calls —
must not precede the first write. Detail: [*Request
lifecycle*](../doc/architecture/views/runtime.md#request-lifecycle-http).

## The views

| View | Answers | File |
|---|---|---|
| **Module** | what exists, who owns it, who may import whom | [`doc/architecture/views/module.md`](../doc/architecture/views/module.md) |
| **Runtime** | what runs when — boot, registry build, request, transaction, concurrency | [`doc/architecture/views/runtime.md`](../doc/architecture/views/runtime.md) |
| **Data** | what persists, who owns it, what is authoritative when stores disagree | [`doc/architecture/views/data.md`](../doc/architecture/views/data.md) |
| **Deployment** | how many processes, what each may do, and how it degrades | [`doc/architecture/views/deployment.md`](../doc/architecture/views/deployment.md) |
| **Gates** | what is mechanically enforced, and what "enforced" is worth | [`doc/architecture/gates.md`](../doc/architecture/gates.md) |
| **Scenarios** | end-to-end threads — installing a module, upgrading a populated database | [`doc/architecture/views/scenarios.md`](../doc/architecture/views/scenarios.md) |
| **Qualities** | how much the forces cost, measured — so a change can fail one | [`doc/architecture/qualities.md`](../doc/architecture/qualities.md) |
| **Risks** | where the implementation and the design demonstrably disagree | [`doc/architecture/risks.md`](../doc/architecture/risks.md) |
| **Measurements** | how these rules were arrived at, and what each cost to learn | [`doc/architecture/MEASUREMENTS.md`](../doc/architecture/MEASUREMENTS.md) |
| **Decisions** | why the architecture is this way, dated and immutable | `doc/adr/` |

Two subsystems document themselves in more depth than any view does:
`odoo/db/README.md` and `odoo/http/README.md` — the latter carries the canonical,
unflattened HTTP call graph.

> **These documents are enforced.** The dependency rules in the module view are
> checked mechanically by `tooling/architecture/layer_check.py` and gated in CI
> (`.github/workflows/architecture.yml`). The rationale for each rule lives in
> the ADRs under `doc/adr/`. Docs explain *why*; the checker guarantees *that*.
> The factual claims *about* the checkers are themselves pinned by
> `tooling/architecture/test_architecture_doc.py`, which runs in the same job:
> contract names and row bodies, pinned counts, the mixin composition, the
> runtime floors, the module inventories, the gate table against the workflow,
> and every **measured** figure, derived from a live run of the checker that
> produces it rather than restated.
>
> **If you add a number to this page, add the assertion with it.** Prose that no
> test reads is prose that has already drifted — `MEASUREMENTS.md` records what
> that cost when it was learned.
>
> That rule has a failure mode worth naming, because this page is the correction
> for it: it selects for claims that are *checkable*, not claims that are
> *important*. Counts and contract names accumulate assertions; the forces above,
> which no checker can verify, went unwritten for as long as the page was
> organised around its own compliance. Both belong here. Neither substitutes for
> the other.

## Where to add code

| You are adding | It goes in | The constraint | Caught by |
|---|---|---|---|
| A dependency-free helper | `odoo/libs/<area>/` | no `odoo` imports; if it needs model data, take it through a `Protocol` (see `libs/locale/number_format.py`) | `libs-is-dependency-free` |
| An Odoo-coupled helper | `odoo/tools/` | may use ORM values and types, never the ORM runtime | `tools-does-not-reach-the-orm-runtime` |
| A new field type | `odoo/orm/fields/` | Layer 1: no `models`/`runtime` imports; reach the model layer through `_recordset.py` | `orm-layer1-below-models-and-runtime` |
| Model behaviour | a mixin under `odoo/orm/models/mixins/` | prefer a leaf nothing else in the composition depends on | `mixin_coupling_check.py` |
| Cache / compute logic | `odoo/orm/components/` | pure Python, collaborators injected, no `pool` or `env` reach | `orm-components-are-pure-python`, `pool_surface_check.py` |
| A persistence primitive | `odoo/db/` | no ORM import; cross the boundary by injection | `db-is-orm-agnostic` |
| An HTTP feature | `odoo/http/` `[features]` | must not import `[serving]` | `http-features-below-serving` |
| A third-party patch | `odoo/_monkeypatches/<module>.py` | expose `patch_module()` (names starting with `_` are helpers and exempt) | `test_architecture_doc.py` |
| An addon | `odoo/addons/<module>/` | import through `odoo.api` / `odoo.fields` / `odoo.models` | `facade-boundary` |
| A package README module index | register it in `PACKAGE_INDEXES` | an unregistered index is gated by nothing | `package_index_check.py` |

Two rules that apply to all of the above: a new module must appear in the
**Subsystem map** in [`views/module.md`](../doc/architecture/views/module.md) if
its package's contents are enumerated there, and a new number written anywhere in
this document set must arrive with the assertion that re-derives it.


