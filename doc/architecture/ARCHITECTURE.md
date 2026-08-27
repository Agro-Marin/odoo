# Odoo Framework Core — Architecture

Scope: the framework core in `odoo/` — ORM, persistence, HTTP, server, module
system, utilities. This page carries context, forces, cross-cutting mechanisms
and the index of the views. Per-addon maps live in
`addons/*/machine_doc_v1/ARCHITECTURE.md`.

| If you are… | Read |
|---|---|
| new to the core | *Context* and *Forces* below, then [`module.md`](module.md) |
| placing new code | *Where to add code* below |
| debugging a runtime path | [`runtime.md`](runtime.md) |
| changing a boundary | [`gates.md`](gates.md), then `doc/adr/` |
| wondering why a rule exists | `doc/adr/`, then the gate's own module docstring |
| deciding whether a decision is owed a record | *When a decision needs a record* in [`doc/adr/README.md`](../adr/README.md) |
| judging a change's cost | [`qualities.md`](qualities.md) |

## Context

The core is not an application. It is the machine that turns a set of installed
*addons* into a running, multi-tenant, database-backed web application.

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

Four properties explain more of the core than any module boundary:

| Property | Consequence |
|---|---|
| **Addons are the product** | the framework ships extension machinery, almost no business behaviour |
| **One process serves many databases** | each with its own registry, schema and installed-module set; no per-process cache without a database key |
| **One deployment runs many processes** (`workers > 0`) | no shared memory; every cross-process signal goes through PostgreSQL |
| **The schema is data** | models, fields and views are rows in `ir_model*`; installing a module mutates the schema at run time; nothing is frozen by a build step |

## Forces

What the architecture optimises for. A design change that makes one worse needs
a reason.

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

The last is this fork's addition and the reason `tooling/architecture/` exists.
Upstream treats the core's internal shape as fixed; `19.0-marin` treats it as
the thing most worth improving, which is safe only while the public surface is
mechanically pinned.

## Non-goals

Each buys something above. An argument appealing to one is already settled.

| Non-goal | What it buys |
|---|---|
| **Merge-compatibility with upstream Odoo** | `19.0-marin` never merges from `19.0` (*Scope and precedence*, `doc/coding_guidelines.rst`), so "it complicates the upstream merge" is not a cost this fork pays — which is what makes core refactoring affordable |
| **Stability of core internals** | the *façade* is the public surface — `odoo.api` / `odoo.fields` / `odoo.models`, each with an explicit `__all__` (ADR-0008); everything behind it is free to move (ADR-0001, ADR-0005) |
| **Business behaviour in the core** | behaviour belonging to a business process belongs in an addon |
| **A build step that freezes shape** | the contributor set is unknown until the module graph is loaded, so nothing resolves at import time |
| **Database-driver portability** | psycopg 3 only — `odoo/db/` imports `psycopg` exclusively, and psycopg2 is not a declared dependency, so a stray import fails anywhere provisioned from `requirements.txt`, CI included, rather than compiling a branch that can never run. A developer virtualenv that installed it for some other reason is the exception, and there the absence does not bite |

## Mechanisms

Five behaviours that cut across every view.

### Models are assembled per database, not defined

A model class in the tree is a *definition*. `orm/registration.py::add_to_registry`
composes the runtime class for a database by multiple inheritance over every
installed module's contribution to that `_name`; `_inherit` collects parents,
`_inherits` sets up delegation, `setup_model_classes(env)` resolves fields across
the graph. `env["res.partner"]` in one database is a different class from the
same name in another.

Consequences: fields cannot be resolved at import time; the framework cannot
import addon-owned models, so it names them by string key (`env["res.users"]`),
gated by `env_model_surface_check.py`. The framework's largest coupling to its
consumer produces no import edge.

### Writes do not reach SQL where you write them

`create()`/`write()` update the field cache, mark ids dirty and schedule
dependent recomputes. The database sees nothing until a flush. A flush is a
fixpoint loop — recomputing one field can dirty another — and non-convergence
raises. Detail: [*Transaction, cache and
flush*](runtime.md#transaction-cache-and-flush).

### Cross-process invalidation runs through PostgreSQL

A registry change is published by `INSERT`ing into a signaling table and keeping
the id the database generated. Every other worker notices on its next
`check_signaling()` and rebuilds its registry or clears the named caches. Any
process-lifetime cache must be registered in `CACHES_BY_KEY`. Detail:
[*Concurrency, and why the process model is
architectural*](runtime.md#concurrency-and-why-the-process-model-is-architectural).

### Access control is a model-layer concern, applied per operation

Every model carries `AccessMixin` (`orm/models/mixins/access.py`), so checks are
methods on the recordset: model-level permissions per CRUD operation,
record-level rules contributing a domain, field-level (`_has_field_access`,
`check_field_access_rights`) and multi-company (`_check_company`).
`_check_access(operation)` returns the accessible subset plus the callable that
explains the refusal, so one code path serves both filtering and raising.

Superuser is not a bypass flag: `sudo()` returns an environment whose `su` is
part of the `(cr, uid, su, context)` interning key. Two recordsets differing
only in privilege are different objects by construction.

### A request is a transaction, and it may run twice

`retrying()` (`service/transaction.py`, not a model method) re-runs the handler
on PostgreSQL serialization and deadlock errors, and a `readonly` route that
writes is re-run on a read/write cursor. Non-transactional side effects — mail,
outbound calls — must not precede the first write. Detail: [*Request
lifecycle*](runtime.md#request-lifecycle-http).

## The views

| View | Answers | File |
|---|---|---|
| **Module** | what exists, who owns it, who may import whom | [`module.md`](module.md) |
| **Runtime** | what runs when — boot, registry build, request, transaction, concurrency | [`runtime.md`](runtime.md) |
| **Data** | what persists, who owns it, what is authoritative when stores disagree | [`data.md`](data.md) |
| **Deployment** | how many processes, what each may do, and how it degrades | [`deployment.md`](deployment.md) |
| **Gates** | what is mechanically enforced, and what "enforced" is worth | [`gates.md`](gates.md) |
| **Scenarios** | end-to-end threads — installing a module, upgrading a populated database | [`scenarios.md`](scenarios.md) |
| **Qualities** | how much the forces cost, measured — so a change can fail one | [`qualities.md`](qualities.md) |
| **Risks** | where the implementation and the design demonstrably disagree | [`risks.md`](risks.md) |
| **Decisions** | why the architecture is this way, dated and immutable — architecture decisions, 0001–0069 | `doc/adr/` |

Rationale is not a view. Each gate's module docstring carries its own, beside
the `MEASURED` block `doc_measured.py` keeps fresh; decisions are in
`doc/adr/`; investigation write-ups are in `agromarin-knowledge/research/`.

Two subsystems document themselves deeper than any view:
`odoo/db/README.md` and `odoo/http/README.md` — the latter carries the
canonical, unflattened HTTP call graph.

> **These documents are enforced.** The dependency rules in the module view are
> checked by `tooling/architecture/layer_check.py`, gated in
> `.github/workflows/architecture.yml`. The claims *about* the checkers are
> pinned by `tooling/architecture/test_architecture_doc.py` in the same job:
> contract names and row bodies, pinned counts, the mixin composition, the
> runtime floors, the module inventories, the gate table against the workflow,
> and every measured figure, derived from a live run of the checker that
> produces it.
>
> **A number added here arrives with the assertion that re-derives it.** Prose
> no test reads has already drifted: a mixin count copied into three files and
> stale in all three, an `env` surface figure two documents agreed on and no run
> reproduced, a ratchet table stating nine floors against thirteen baseline
> files.
>
> That rule selects for claims that are *checkable*, not claims that are
> *important*. The forces above, which no checker can verify, belong here too.

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

Two rules over all of the above: a new module must appear in the **Subsystem
map** in [`module.md`](module.md) if its package's contents are enumerated
there, and a new number must arrive with the assertion that re-derives it.
