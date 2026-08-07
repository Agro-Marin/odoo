# Odoo Framework Core — Architecture

The buildable description of the framework core in `odoo/` — ORM, persistence,
HTTP, server, module system, utilities. It states what each part owns, which
dependencies are legal, how a request and a transaction actually run, and where
new code goes. It is the framework-level counterpart to the per-addon
`machine_doc_v1/ARCHITECTURE.md` maps.

Read it by task:

| Task | Sections |
|------|----------|
| Orienting in the core | Subsystem map · Ownership and legal direction · Where to add code |
| Placing new code | The ORM layer model · Enforced dependency rules · Seams |
| Debugging a runtime path | Lifecycles |
| Changing a boundary | Quality gates · Known boundary exceptions · `doc/adr/` |

> **This document is enforced.** The dependency rules below are checked
> mechanically by `tooling/architecture/layer_check.py` and gated in CI
> (`.github/workflows/architecture.yml`). The rationale for each rule lives in
> the ADRs under `doc/adr/`. Docs explain *why*; the checker guarantees *that*.
> The factual claims *about* the checkers on this page are themselves pinned by
> `tooling/architecture/test_architecture_doc.py`, which runs in the same job:
> contract names and row bodies, pinned counts, the mixin composition, the
> runtime floors, the module inventories, the gate table against the workflow,
> and every **measured** figure, derived from a live run of the checker that
> produces it rather than restated.
>
> **If you add a number to this page, add the assertion with it.** Prose that no
> test reads is prose that has already drifted — the appendix records what that
> cost when it was learned.

## Subsystem map

```
odoo/
├── orm/            The ORM, as an explicit 4-layer architecture (see below)
│   ├── primitives, parsing, validation, constants, _typing   (Layer 0)
│   ├── fields/, domain/                                       (Layer 1)
│   ├── models/  (BaseModel + 23 mixins, metaclass)            (Layer 2)
│   ├── runtime/ (Environment, Registry, Transaction, backend) (Layer 3)
│   ├── components/  pure-Python cache / compute / unit-of-work (cross-cutting)
│   ├── _recordset, model_test_env                               (seams)
│   └── decorators, registration, helpers                        (cross-cutting)
├── api/ · fields/ · models/   Thin public re-export shims over orm/ (stable imports)
├── db/             Decomposed sql_db.py + the resilience tier (flat modules)
│   ├── [foundation]   errors, dsn, utils
│   ├── [connectivity] pool, cursor, ddl, schema, savepoint, schema_cache,
│   │                  bulk, lifecycle
│   └── [resilience]   breaker (circuit breaker w/ backoff + single prober),
│                      lag (replica apply-lag ceiling, db_replica_max_lag),
│                      budget (process-wide connection semaphore),
│                      leaks (who holds a checked-out connection),
│                      reaper (idle per-DSN pool reaping),
│                      metrics (SQL per cursor) · stats (what the pool did)
├── http/           Decomposed http.py (flat modules)
│   ├── [serving]   application, dispatcher, routing, session, request_class,
│   │               _serve, _response, wrappers, stream, _csrf, controller,
│   │               core (the `request` proxy + its LocalStack), helpers
│   └── [features]  openapi (OpenAPI 3.1 from the routing map),
│                   _params (annotation-driven @route(typed=True) coercion),
│                   geoip, constants, exceptions, _protocols
├── service/        Process lifecycle + the servers
│   ├── server, _base_server, _threaded (ThreadedServer + EventServer),
│   │   _prefork, _worker, _watcher, wsgi, _cron, lifecycle
│   └── transaction (the retrying() primitive), db, model, security, common,
│       _env, _helpers, _db_helpers, _dump_scanner, _metrics
├── modules/        The module graph (iterated by phase, dependency depth,
│   │               then name) and what loads it
│   └── module_graph, module, loading, migration, db, neutralize,
│       registry/ (a re-export shim — `Registry` itself is Layer 3, in
│                  `orm/runtime/registry.py`)
├── tools/          Odoo-COUPLED utilities (need ORM / config / runtime)
│   ├── assets/     Server-side asset pipeline (esbuild + ESM graph/bridges/
│   │               registry/lexer)
│   ├── pdf/        PDF reading/writing/merging + `PdfSigner` (CMS/PKCS#7)
│   └── babel_extractors/   Babel message extractors for Python and JavaScript
├── libs/           Odoo-AGNOSTIC utilities (no framework dependency)
├── _monkeypatches/ Explicit, import-hook-driven third-party patches
│                   (`PatchImportHook` on `sys.meta_path`; every
│                   non-underscore submodule exposes `patch_module()`)
├── cli/            Command-line entry points
├── upgrade_code/   Dated source-rewrite scripts run by `odoo-bin upgrade_code`
└── addons/         The bundled base addons — `base` plus the `test_*` suites,
                    and only those. (`web` and the rest of the standard addons
                    live in the repo-root `addons/`, the second tree described
                    under *Public import surface*; this map is rooted at
                    `odoo/odoo/`.) The framework's own consumer, governed by
                    `facade-boundary`
```

> **Notation.** A name ending in `/` is a directory and a bare name is a module,
> both checked against the tree by `tooling/architecture/subsystem_map_check.py`.
> A name in `[brackets]` is a **logical grouping, not a directory** — `db/` and
> `http/` are flat packages, and the bracketed labels group their modules by
> role. Where the map enumerates a package's contents it must do so
> exhaustively, per kind; the gate fails on a missing module or subpackage.
>
> **The bracketed tiers carry contracts of their own** —
> `db-resilience-below-connectivity` and `http-features-below-serving`, both in
> the table below. Filing a module in the right bracket is therefore a decision,
> not a caption: `db/errors.py` (with `dsn`/`utils`) imports nothing else in
> `db/` and is used by both tiers, so it is `[foundation]`, not
> `[connectivity]`; `http/helpers.py` imports `core` and is imported by
> `dispatcher`/`_serve`/`request_class`, so it is `[serving]`, not `[features]`.

### Ownership and legal direction

Each package owns one concern and may only depend downward. Where a row names a
contract, the direction is a CI gate rather than a convention.

| Package | Owns | Must not import | Contract |
|---------|------|-----------------|----------|
| `libs/` | Odoo-agnostic utilities | any `odoo.*` except `odoo.libs` | `libs-is-dependency-free` |
| `db/` | connections, cursors, DDL, pool resilience | `odoo.orm`, `odoo.models`, `odoo.fields`, `odoo.api` | `db-is-orm-agnostic` |
| `orm/` | models, fields, domains, Environment/Registry/Transaction, cache & compute | `odoo.service`, `odoo.http`, `odoo.cli` | `orm-below-the-serving-tier` |
| `tools/` | Odoo-coupled utilities | `odoo.orm.runtime` (Layers 0–1 stay allowed) | `tools-does-not-reach-the-orm-runtime` |
| `modules/` | the module graph and what loads it | `odoo.addons.<module>` | `core-does-not-depend-on-addons` |
| `http/` | the WSGI application, routing, dispatch, sessions | `odoo.addons.<module>` | `core-does-not-depend-on-addons` |
| `service/` | process lifecycle, the servers, cron, RPC services | `odoo.addons.<module>` (2 pinned exceptions) | `core-does-not-depend-on-addons` |
| `cli/` | command entry points | `odoo.addons.<module>` | `core-does-not-depend-on-addons` |
| `addons/` | the bundled base addons | `odoo.orm.*` | `facade-boundary` |

`_monkeypatches/` sits outside the direction rules by construction: it runs
before anything else (see **Process boot**) and patches third-party modules
only.

### Public import surface

Addon code imports from the stable façades — **`odoo.api`, `odoo.fields`,
`odoo.models`** — never from `odoo.orm.*` directly. These `__init__.py` re-export
shims let the ORM's internal layout evolve without breaking addon imports. Each
declares an explicit `__all__`, and the boundary is **enforced**: the
`facade-boundary` contract fails CI if any file under either addon tree imports
`odoo.orm.*` at runtime (`if TYPE_CHECKING:` exempt). Both trees live inside this
checkout: `odoo/addons/` (module name `odoo.addons.*`) and the repo-root
`addons/` (module name `addons.*`, mounted at `odoo.addons.*` by the addons-path
loader at runtime). See ADR-0008.

## The ORM layer model

The ORM is organised as strict layers; **runtime imports point downward only.**
Cross-layer references for *typing* are allowed when guarded by
`if TYPE_CHECKING:` (they never execute), which is how the layers share types
without forming import cycles.

```
Layer 3  runtime/      Environment, Registry, Transaction        ─┐ imports
Layer 2  models/       BaseModel, mixins, metaclass, table objs   │ downward
Layer 1  fields/ domain/   Field types, domain AST + optimizer    │ only
Layer 0  primitives parsing validation constants _typing         ─┘

         components/   FieldCache · ComputeEngine · UnitOfWork · ModelGraph
                       Beside the stack, not under it: Layers 2 and 3 import
                       it, Layers 0 and 1 never do. Pure Python — no odoo
                       imports at runtime except odoo.libs. Collaborators
                       injected.
```

- **Layer 0** imports no higher *ORM* layer (the enforced
  `orm-layer0-is-foundational` rule). It may still use dependency-free helpers
  from `odoo.tools` and `odoo_rust`: the invariant is "nothing from the ORM
  above it", not "nothing from `odoo`". Read that precisely — the contract
  forbids `orm.fields`, `orm.domain`, `orm.models`, `orm.runtime` **and**
  `orm.components`, plus the three façades `odoo.fields`, `odoo.models` and
  `odoo.api`, because re-export shims are the obvious way round a rule written
  only against `odoo.orm.*`. Of that permission it currently exercises only the
  first — `primitives.py` takes the `SQL` builder from `odoo.tools`, and no
  Layer-0 module imports `odoo_rust` at all (it enters the ORM at `helpers.py`,
  `models/mixins/read.py` and `runtime/environment.py`). Both halves are
  permission, not practice; do not read the pairing as a claim that Layer 0
  depends on the Rust extension.
- **Layer 1** (`fields`, `domain`) uses no higher ORM layer, and Layer 1
  imports `components/` nowhere. As with Layer 0 the rule is about *ORM*
  layers: both packages import `odoo.tools`, `odoo.libs` and `odoo.exceptions`
  freely.
- **Layer 2** (`models`) builds on Layers 0–1, plus `components/`
  (`mixins/recompute.py` → `components.recompute.RecomputeScheduler`).
- **Layer 3** (`runtime`) builds on Layers 0–2 and owns the `components/`
  instances — `Transaction` constructs `FieldCache`, `ComputeEngine`,
  `UnitOfWork` and `OrmCore`.
- **`components/`** is the cache/compute/unit-of-work engine — pure Python apart
  from `odoo.libs` (which is itself dependency-free; `model_graph.py` imports
  `Collector` from it), so it is unit-testable without an `Environment`,
  `Registry`, or database. Collaborators are injected (ADR-0002). Framework code
  reaches the per-transaction `FieldCache`/`ComputeEngine` through the curated
  id-level facade **`env._core`** (`OrmCore`, defined in `components/core.py`);
  the raw objects stay private to `Transaction` (`_cache_store`/
  `_compute_engine`), and `env.cache` is the legacy recordset-level wrapper
  (ADR-0010).
  > **What "pure" does and does not mean.** The contract is about *this
  > package's* imports, and it holds. It does **not** mean a component can be
  > imported in isolation: `import odoo.orm.components.model_graph` executes the
  > parent package first, and `orm/__init__.py`'s last line is `import
  > odoo.init` — the framework bootstrap, which applies the `_monkeypatches` and
  > so loads `babel` (and, through the patched modules, `lxml`). That is why
  > `components/tests/conftest.py` stubs the `odoo` / `odoo.orm` /
  > `odoo.orm.components` namespace packages rather than importing them. The
  > purity that is real is *dependency direction*, not import isolation; treat
  > "unit-testable" as "needs no ORM runtime objects", not "costs nothing to
  > import".

`orm/__init__.py`'s docstring states this same layer model in code, member by
member. Both now name every member at the layer the gate enforces, and where a
doc and the gate ever differ, `layer_check.py`'s `CONTRACTS` wins — it is the
definition that actually runs.

## Enforced dependency rules

| Contract | Rule | Status |
|----------|------|--------|
| `libs-is-dependency-free` | `odoo/libs/**` must not import `odoo.*` (except `odoo.libs`) | ✅ clean |
| `db-is-orm-agnostic` | `odoo/db/**` must not import `odoo.orm/models/fields/api` | ✅ clean |
| `tools-does-not-reach-the-orm-runtime` | `odoo/tools/**` must not import `odoo.orm.runtime` (Layers 0–1 stay allowed) | ✅ clean |
| `orm-helpers-and-registration-stay-below-runtime` | `orm/helpers.py` & `orm/registration.py` must not import `orm/runtime` | ✅ clean |
| `orm-components-are-pure-python` | `odoo/orm/components/**` must not import `odoo.*` (except `odoo.libs`) | ✅ clean |
| `orm-layer0-is-foundational` | Layer-0 (`primitives`, `parsing`, `validation`, `constants`, `_typing`) imports no higher ORM layer | ✅ clean |
| `orm-layer1-below-models-and-runtime` | `orm/fields` & `orm/domain` must not import `orm/models` or `orm/runtime` | ✅ clean |
| `orm-models-below-runtime` | `orm/models` (Layer 2) must not import `orm/runtime` (Layer 3) | ✅ clean |
| `orm-seams-stay-below-models-and-runtime` | `orm/_recordset` & `orm/decorators` must not import `orm/models` or `orm/runtime` | ✅ clean |
| `facade-boundary` | addon code (`odoo/addons/**` **and** the repo-root `addons/**`) must not import `odoo.orm.*` (use `odoo.api`/`odoo.fields`/`odoo.models`) | ✅ clean |
| `core-does-not-depend-on-addons` | core packages must not import `odoo.addons.<module>` (bare `odoo.addons` for `__path__` discovery is fine) | ✅ 0 new, 2 pinned rules |
| `db-resilience-below-connectivity` | `db/` `[resilience]` (breaker, lag, budget, leaks, reaper, metrics, stats) must not import `[connectivity]` (pool, cursor, ddl, schema, savepoint, schema_cache, bulk, lifecycle) | ✅ clean |
| `http-features-below-serving` | `http/` `[features]` (openapi, `_params`, geoip, constants, exceptions, `_protocols`) must not import `[serving]` | ✅ clean |
| `orm-below-the-serving-tier` | `odoo/orm/**` must not import `odoo.service`, `odoo.http` or `odoo.cli` — the serving tier runs on the ORM, never the reverse | ✅ clean |

**The eight original boundaries are clean at zero** — no tolerated exceptions.
The gate is **drift-zero**: any *new* crossing fails CI. A genuinely unavoidable
exception must be pinned (annotated) in `layer_check.py`'s `KNOWN_VIOLATIONS`, so
it stays visible and cannot multiply.

Three scope caveats the "✅ clean" column does not show, all by design:

- **Every contract is a DIRECT-edge rule, never transitive.**
  `orm-layer1-below-models-and-runtime` stops `odoo/orm/fields` importing
  `odoo.orm.runtime`; it says nothing about `odoo/orm/fields` →
  `odoo.tools.something` → `odoo.orm.runtime`. Transitivity is deliberately
  *not* the fix: `tools/` is the Odoo-coupled utility layer by design, so in a
  transitive graph everything reaches everything through it, and the rule would
  need a large, low-signal pinned baseline. The useful invariant is narrower —
  utilities may use ORM *values and types*, but must not reach the *runtime* —
  and it is enforced as `tools-does-not-reach-the-orm-runtime`, which holds at
  zero and rejects that exploit. Read the contracts as "no direct edge", and add
  a targeted contract when a conduit matters.
- **Test files are not scanned — but `odoo/tests/` is not test files.**
  `layer_check.iter_source_files()` drops any path with a `tests` component,
  plus `conftest.py` and `test_*.py`, because tests legitimately import across
  boundaries for fixtures and bootstrap. The one carve-out is
  `_CORE_TEST_FRAMEWORK_PACKAGE = ("odoo", "tests")`: that package is the
  shipped test *framework*, so inside it only its own `test_*.py` and
  `conftest.py` are dropped and `case.py`, `common.py`, `http.py` and the rest
  **are** scanned. The next bullet is the proof — if the package were skipped
  wholesale, its exemption from `core-does-not-depend-on-addons` would be dead
  code. (`py_cycle_check.py` carried the uncarved version of this filter and
  reported on 323 modules instead of 338; see its bullet below.)
- **`odoo.tests` is exempt from `core-does-not-depend-on-addons`** (via
  `CORE_PACKAGES_EXEMPT_FROM_ADDON_CONTRACT`): the test *framework*'s job is to
  drive application code, and its one addon reach (`tests/http.py` →
  `odoo.addons.bus`) is already deferred and guarded by
  `if "bus.bus" in self.env.registry:`. Every other core package is in scope,
  asserted by `test_core_source_covers_every_core_package`.

`core-does-not-depend-on-addons` is the mirror of `facade-boundary`: that one
stops addons reaching into ORM internals, this one stops the framework depending
on its own consumer. It ships with **two pinned `KNOWN_VIOLATIONS` rules**
(`odoo.service` → `odoo.addons.base.models.ir_cron` / `…ir_job`), which the
report expands to **4 tolerated edges** — one per call site. Both are intentional
rather than debt, and the reasoning is in **Known boundary exceptions** below.

## Coupling the import graph cannot see

`layer_check.py` reasons about **import** edges. `BaseModel` is composed from 23
`__slots__ = ()` mixins by multiple inheritance — 18 public (`CreateMixin` …
`AccessMixin`) plus 5 private (`_PropertiesMixin`, `_QueryMixin`,
`_MagicFieldsMixin`, `_ModelMetadataMixin`, `_ConstraintsMixin`) — and they
collaborate through `self`, which produces no import at all. The framework's most
intricate coupling surface therefore moves no import gate.
`tooling/architecture/mixin_coupling_check.py` reconstructs that call graph and
ratchets it (`max_scc`, `cyclic_edges`, `scc_without_base`) exact-mode like
`tooling/ratchet/` — **twice**, because there are two graphs and they disagree.

**Through `self`, the graph is a DAG.** `cyclic_edges` is 0. The four private
mixins are what got it there: the metadata/properties/magic-field split took
`base.py` out of a nine-unit cycle, and `_QueryMixin` broke the last one by
giving *query construction* a home of its own. Note what that did and did not
do: the cycle was `read` ⇄ `search`, and only the **back-edge `read → search` is
gone** — `read` now reaches query construction through `_query` instead.
`search → read` is still there, and is fine: one direction is a DAG edge. Five
units depend on `_query` (`read`, `search`, `recompute`, and two of the
`read_group` units).

**Through the model, it is too.** A mixin is a fragment of *one class*, so
calling a sibling's method on another recordset of the same model couples
exactly as much as calling it on `self`, and a `self`-only collector cannot see
it. Following locals bound from `self.browse(…)`, `self.filtered(…)`,
`self.sudo()` and the rest (`RECORDSET_PRODUCERS`) adds 8 edges — and the first
such measurement found a cycle the `self`-only view could not: **`base.py` ⇄
`create`**, where `orm/models/base.py:159` calls `self.create(…)` in
`name_create` while `create.py` called `_validate_fields` on recordsets `self`
never names.

It was broken the same way its predecessors were, by moving behaviour off the
composition root: `_constraint_methods` and `_validate_fields` live on a
`_ConstraintsMixin` leaf (`mixins/_constraints.py`), so `create` and `write`
reach the constraint machinery without touching `base.py`. **A leaf that nothing
in the composition depends on cannot close a cycle** — that is the design rule
for new mixins.

Both views are ratcheted at zero (`recordset_max_scc` 1,
`recordset_cyclic_edges` 0, `recordset_scc_without_base` 1), so a cycle spelled
through a recordset fails CI even though the `self`-only numbers would stay
clean.

The checker's numbers are cross-checked against the runtime
`BaseModel.__mro__`, not just against themselves. It counts *file-level*
units — 28, since `read_group/` contributes five (`_empty`, `fill`, `format`,
`mixin`, `sql`) and `base.py` is itself a unit — not the 23 bases.

```bash
python tooling/architecture/mixin_coupling_check.py            # report
python tooling/architecture/mixin_coupling_check.py --check    # CI
python tooling/architecture/mixin_coupling_check.py --explain search read
```

## Seams that keep the layers decoupled

Every downward-only rule above has a counterpart seam that lets the lower layer
still be *driven* by the upper one. These are the extension points; adding a new
cross-layer dependency means adding a seam, not an import.

- **`db/` ↔ ORM:** the cursor's flushing savepoint is injected via
  `BaseCursor._flushing_savepoint_cls` (`orm/runtime/savepoint.py` assigns
  `_OrmFlushingSavepoint` at import), so `db/` never imports the ORM (ADR-0003).
- **`components/` ↔ runtime:** `FieldCache`/`ComputeEngine` take callbacks for
  SQL and recompute, so the engine never imports `Environment`.
- **Layer 1 ↔ `BaseModel`:** `fields/` and `domain/` recognise recordsets and
  `_search` overrides through `orm/_recordset.py`, into which the model layer
  injects `BaseModel` at import time via `set_base_model()` — so Layer 1 never
  imports Layer 2 (ADR-0001).
- **CRUD ↔ persistence backend:** the model mixins (`create`/`write`/`read`/
  `search`/`unlink`) dispatch row I/O through `env.backend` — `None` takes the
  PostgreSQL fast path (SQL inline), a non-`None`
  `runtime/backend.py::InMemoryBackend` owns the DB-free variant. Production CRUD
  no longer sniffs the test backend via `transaction.storage` (ADR-0011).
- **Framework ↔ addon-owned models:** the core reaches application models by
  string key (`env["res.users"]`), never by import. That is deliberate, and it is
  the one seam with no import edge at all, so it has its own gate — see
  `env_model_surface_check.py` below.

## Lifecycles

Four runtime paths a reader has to hold to debug the core. Each is a sketch;
where a canonical unflattened version exists it is named.

### Process boot

```
odoo-bin
└─ odoo.cli.main()                     cli/command.py — bootstrap parse, pick command
   └─ <Command>.run(args)              cli/server.py for the default `server` command
      └─ service.lifecycle.start()
         ├─ load_server_wide_modules()
         ├─ choose EventServer | PreforkServer | ThreadedServer
         └─ server.run(preload, stop)
            └─ service.lifecycle.preload_registries(dbnames)
               └─ Registry.new(db, update_module=…)      one registry per database
```

Before any of that, importing `odoo.orm`, `odoo.modules` or `odoo.cli.command`
executes **`odoo/init.py`**, the framework bootstrap, in this order: enforce
`MIN_PY_VERSION`, probe the mandatory `odoo_rust` native extension (a failed
import here is a hard, explained error, not a fallback), retune the GC
thresholds, then `_monkeypatches.patch_init()`. Anything that must be patched
before third-party modules load has to run from there.

The other runtime floor is enforced far later and by a different subsystem:
`db/pool.py` compares the server against `MIN_PG_VERSION` at connect time and
raises `PoolError`. Both constants live in `odoo/release.py` and are named here
rather than restated — a floor written into prose is a second copy that drifts.

Which server object is chosen is a deployment decision, not an architectural
one: `workers = 0` gives `ThreadedServer` (debugger-friendly, one process),
`workers > 0` gives `PreforkServer`, and `odoo.evented` gives `EventServer`.
They differ in process model only; every one of them ends in the same
`preload_registries` → `Registry.new` path.

### Registry build

`Registry.new()` is the most expensive operation in the system and the only way
a database's model classes come into existence. It refuses to run against a
system or template database, allocates the registry, sets up cross-process
signalling, and then hands off to `modules.loading.load_modules()`, whose phases
are methods on `_ModuleLoader`:

```
Registry.new(db)
├─ setup_signaling()                      cross-process registry/cache sequences
└─ load_modules(registry, …)
   ├─ bootstrap()                         `base` present? graph seeded?
   ├─ run_pre_upgrade_scripts()           update only
   ├─ capture_database_field_metadata()   update only, before the schema moves
   ├─ open_environment_and_load_base()    first Environment; `base` data loaded
   ├─ load_languages()
   ├─ process_module_requests()           update only: to-install / to-upgrade
   ├─ converge_module_graph()             load modules until the graph is stable
   ├─ finish_registry_setup()             _setup_models__ / init_models
   ├─ run_end_migrations()                update only
   ├─ finalize_constraints()              deferred constraints, then NOT NULL
   ├─ uninstall_removed_modules()         update only; may force one full reload
   ├─ validate_custom_views()             update only
   └─ register_model_hooks() · check_null_constraints()
```

Two consequences worth knowing before touching this path:

- **The graph is iterated by phase, then dependency depth, then name** — never by
  filesystem order. A module's data loads only after every dependency's.
- **`uninstall_removed_modules()` can raise `_UninstallRequiresReload`**, which
  makes `load_modules` call `Registry.new()` again from inside itself. Code that
  assumes one registry build per process start is wrong.

After `load_modules` returns, `Registry.new` marks the registry ready, calls
`_ensure_field_triggers()`, and `signal_changes()` so other workers reload.

### Request lifecycle (HTTP)

```
WSGI  →  Application.__call__  →  Request (_post_init: session + db)
      →  _serve_static | _serve_nodb | _serve_db
            _serve_db: registry cursor → Environment → ir.http._match
                match  → service.transaction.retrying(_serve_ir_http):
                             ir.http._authenticate → ir.http._pre_dispatch
                             → Dispatcher.pre_dispatch → Dispatcher.dispatch
                             (→ ir.http._dispatch → endpoint)
                             → ir.http._post_dispatch
                no match → retrying(_serve_ir_http_fallback):
                             ir.http._serve_fallback → ir.http._post_dispatch
            → cr.close() → response
```

Three details the sketch flattens, all of them claims about **order**:

- **`retrying()` lives in `odoo/service/transaction.py`**, not on a model. It
  re-runs the callable on PostgreSQL serialization/deadlock errors, rewinding
  uploaded files between attempts.
- **Commit and session-save both happen *inside* the sketch, not after it.**
  `env.cr.commit()` is the last thing `retrying()` does once its callable
  returns, and the session is written earlier still — by
  `Dispatcher.post_dispatch` → `Request._save_session()`, so *before* that
  commit. `_serve_db` itself only closes the cursor, in its `finally`.
- **RO → RW promotion.** A route declared `readonly` first runs on a read-only
  cursor. If its handler writes, `psycopg.errors.ReadOnlySqlTransaction` is
  caught, a read/write cursor is acquired and **the handler runs a second time**
  — so non-transactional side effects (emails, outbound calls) must not precede
  the first write.

No text search can settle an ordering claim: every gate that "covers" the three
above is a grep, and a commit moving the commit above the dispatcher call would
satisfy all of them. The runtime proof is
`addons/test_http/tests/test_lifecycle_order.py`, which patches
`Request._save_session` and *both* cursor classes and reads the sequence off the
serving thread. Observed: `[save_session, commit]` normally, and
`[save_session, save_session, commit]` on the promoted path — the double-run
showing up in the same trace as the ordering. (Both cursor classes, because
under `HttpCase` the request's `env.cr` is a `TestCursor`, which subclasses
`BaseCursor` rather than `Cursor`; instrumenting `Cursor.commit` alone observes
nothing and reads as "`retrying()` never commits".)

`Dispatcher` has three subclasses (`HttpDispatcher`, `JsonRPCDispatcher`,
`Json2Dispatcher`) selected by `routing["type"]`.

The canonical, unflattened call graph — every stage, plus what each one is
responsible for — is **`odoo/http/README.md`**. That file also carries `http/`'s
module map, which `package_index_check.py` gates.

### Transaction, cache and flush

One `Transaction` per cursor (`cr.transaction`), created lazily by the first
`Environment` built on that cursor. It owns the registry reference and the
per-transaction machinery:

```
Cursor ──── transaction ────┬─ registry          the model classes
                            ├─ _cache_store      FieldCache   (field values, dirty ids)
                            ├─ _compute_engine   ComputeEngine (pending recomputes)
                            ├─ core              OrmCore  ← the curated facade, env._core
                            ├─ unit_of_work      UnitOfWork (the fixpoint loops)
                            ├─ backend           None = PostgreSQL · InMemoryBackend = DB-free
                            └─ envs              interned Environments
```

`Environment(cr, uid, context, su)` is **interned** per `(cr, uid, su, context)`:
constructing one with the same key returns the existing object. Environments are
therefore cheap and identity-comparable, and any per-request state must live on
the transaction or the request, never on an `Environment` you happen to hold.

**Writes do not reach SQL where you write them.** `create()`/`write()` update the
field cache, mark ids dirty, and schedule dependent computes; the database sees
nothing until a flush. A flush is a *fixpoint loop*, because recomputing one
field can dirty another:

```
env.flush_all()
└─ UnitOfWork.run_flush_loop(recompute_fn, flush_fn)     ≤ MAX_FIXPOINT_ITERATIONS (1000)
   ├─ recompute_fn(field)  → model._recompute_field(field)
   └─ flush_fn(models)     → model.flush_model()   inside one cr.pipeline()
                              ├─ _recompute_fields(stored computed fields)
                              └─ _flush()  pops the dirty ids → UPDATE
```

Non-convergence is an error, not a warning: the loop raises unless the context
carries `tolerant_recompute`, and `UnitOfWork` also carries a stall detector so a
loop that stops making progress fails in seconds instead of grinding to the
iteration cap. `flush_model()` / `flush_recordset()` are the scoped versions and
both short-circuit when nothing is pending or dirty.

Row I/O at the bottom of all of this goes through `env.backend`, the ADR-0011
port described under **Seams** — which is what lets the whole ORM run against
`InMemoryBackend` with no database at all.

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
**Subsystem map** if its package's contents are enumerated there, and a new
number written on this page must arrive with the assertion that re-derives it.

## Running the checks

Every checker in the table below takes the same three forms — bare for a
human-readable report, `--check` for CI (exit 1 on a new violation), `--json`
for a machine-readable one — so the two named here are the pattern, not the set:

```bash
python tooling/architecture/layer_check.py          # human-readable report
python tooling/architecture/layer_check.py --check   # CI mode: exit 1 on new violations
python tooling/architecture/layer_check.py --json     # machine-readable

python tooling/architecture/subsystem_map_check.py --check   # the map above vs the tree
```

To reproduce the whole job, self-test first and then run the thirteen in the
order the workflow does — the self-test is a blocking step, because a checker
whose own logic is broken reports green over code it never read:

```bash
python -m pytest tooling/architecture/ -q
for gate in layer_check mixin_coupling_check subsystem_map_check \
            package_index_check env_surface_check pool_surface_check \
            env_model_surface_check worker_thread_surface_check \
            libs_facade_check py_cycle_check js_layer_check js_cycle_check \
            named_export_coherence; do
    python "tooling/architecture/$gate.py" --check || echo "FAILED: $gate"
done
```

## Quality gates beyond the boundaries

The Python boundary checker (ADR-0005) is one gate among several. The
`Architecture Boundaries` workflow runs **twenty-four** blocking checkers — it first
runs `pytest tooling/architecture/` to self-test them, then:

| Gate | What it locks |
|------|---------------|
| `layer_check.py` | the Python layering contracts in the table above |
| `mixin_coupling_check.py` | the `self`-call graph the import graph cannot see |
| `env_surface_check.py` | the Layer→runtime `env` seam, and that every reached `Environment` member exists |
| `pool_surface_check.py` | the Layer→runtime `pool` seam: private reach, member validity, and `components/` at zero |
| `env_model_surface_check.py` | the framework's string-keyed dependency on addon-owned models (`env["res.users"]`), which `core-does-not-depend-on-addons` cannot see — *which* models (exact set) **and** which subtrees may reach none |
| `worker_thread_surface_check.py` | inline `threading.current_thread().<attr>` reads of per-request bookkeeping (`dbname`, `cursor_mode`, …), which mypy and `layer_check` cannot see |
| `libs_facade_check.py` | addon code **and every core package** importing `odoo.libs` **areas**, never their leaf modules |
| `py_cycle_check.py` | Python import cycles in the core — the direction gates cannot see them |
| `subsystem_map_check.py` | the **subsystem map above** against the actual tree |
| `package_index_check.py` | a package README's module index against the package |
| `js_layer_check.py` | the web addon's Feature-Sliced JS layers |
| `js_cycle_check.py` | ESM import cycles across **every** addon's client source |
| `named_export_coherence.py` | `import { x }` with no matching `export` |
| `js_suite_parity.py` | the web addon's test tree against its source tree — a moved test must move with what it tests |
| `js_layer_cohesion.py` | each file filed with what it serves, not with what it resembles |
| `js_import_resolution.py` | every first-party specifier naming a real file |
| `js_self_bridge.py` | no source module resolving itself through the loader |
| `js_patch_blind_facade.py` | a service's own callers going through its facade |
| `js_function_length.py` | the web addon's JS function-length budget |
| `js_private_access.py` | the cross-module private-access budget (`_member` reached past a module) |
| `js_service_shape.py` | a service handing back an instance, not a literal |
| `js_public_surface.py` | the web addon's published JS surface, as a ratchet |
| `naming_vocabulary.py` | the §2.4 method-naming verb vocabulary |
| `xml_reference_coherence.py` | view-arch strings (`widget=`, `js_class=`, `t-call`) against the JS registries and templates |

Four of those are the same argument as `mixin_coupling_check.py`, applied to
surfaces the import graph cannot see. Each states an invariant you have to
respect when writing code in the ORM:

- **`env_surface_check.py` — Layers 1 and 2 reach the runtime through `self.env`,
  not through imports.** `orm-layer1-below-models-and-runtime` and
  `orm-models-below-runtime` are clean and always will be, because that reach
  produces no import edge. Measured, **Layer 1 (`orm/fields`) is the heaviest
  consumer of `Environment`'s private internals — wider than Layer 2**
  (4 unsanctioned private members against 2, 10 accesses against 3). Those are
  the *unsanctioned* privates — the ones the gate pins; the report's own header
  prints the raw private width (6 and 4), which includes the members
  `SANCTIONED_PRIVATE` blesses, so a run and this page will not show the same
  two numbers. The layering
  story is true of the import graph and false of the runtime graph, which is why
  this gate exists. It also validates that every reached member *exists*, which
  covers the four `env.__dict__["_field_cache_memo"]` string-key hot paths:
  renaming that member is caught by nothing else (ruff is blind; mypy sees only
  the 2 plain-attribute sites), and the `except KeyError` fallback would silently
  turn the fast path into a permanent slow one.
- **`env_model_surface_check.py` — the set of addon-owned models the framework
  may name is closed.** It ratchets *which* models are reached by string key, as
  an exact set. That set is flat across the whole scope, so on its own it answers
  "which models", never "who may reach them" — and a package reaching an
  **already-known** model adds nothing to the set. So it also pins seven subtrees
  at *zero* model reaches (`orm/components`, `libs`, `db`, the
  `api`/`fields`/`models` shims, `_monkeypatches`), each of which already claims
  the property for an independent reason, so a first reach there is a
  contradiction rather than a cost. Deliberately not the full (package, model)
  cross-product — that would fire on every ordinary new reach inside a package
  that already reaches models, which is noise.
- **`pool_surface_check.py` — the Registry is the *second* runtime channel, via
  `self.pool`.** It produces no import edge either, and shows the same inversion,
  though on one axis rather than three: **`orm/fields` (Layer 1) touches the
  Registry at 30 sites against `orm/models`' 28**, and uses 5 `pool[<model>]`
  subscripts against Layer 2's 3. Be precise about the rest: Layer 2 reaches
  *more distinct* members than Layer 1 (15 against 9), and it has private reaches
  of its own — `_ensure_field_triggers`, `_init_modules`,
  `_database_translated_fields` and `_database_company_dependent_fields`, pinned
  beside `_relation_reflections`. The claim that survives measurement is volume,
  not "Layer 2 touches nothing private".

  The scope of both seam gates lives in
  `tooling/architecture/_orm_layer_scope.py`, shared so they cannot drift apart,
  with a completeness test that forces every ORM module to be given a layer or an
  argued exemption. The gate ratchets three invariants — no unsanctioned
  `pool._private` from Layers 0–2, every referenced member must exist on
  `Registry`, and `components/` must not touch `pool` at all (the runtime half of
  the purity claim `orm-components-are-pure-python` makes about imports).
  Public-surface *width* is reported, not ratcheted, on the same rationale as the
  `env` gate: Layer 1 consulting `pool.field_inverses` is the design working, and
  a gate firing on a 10th public member would punish ordinary work.
  Its sharpest finding is a lifecycle one: `Registry._relation_reflections` is
  created inside `init_models`' `try:` and `del`-eted in its `finally:`, so it
  exists *only* for that call — and `fields/relational/many2many.py` mutates it
  from Layer 1, which works solely because `update_db` runs inside that window.
  Nothing declares that ordering, and nothing but an `AttributeError` during
  module installation would catch its violation.
- **`py_cycle_check.py` — direction rules are blind to cycles.** Every edge of a
  cycle can sit inside one layer and cross no boundary. Python hides this better
  than ESM, which is what lets it accumulate: a partially-initialised module is a
  live object, so a cycle usually *works* until an entry point changes.
  Function-local imports are deliberately not edges — a deferred import is the
  sanctioned way to break a cycle, so counting it would flag every seam that
  already fixes the problem. Four are pinned (`service`, `modules`, `cli`,
  `tests` — all the benign package↔submodule shape); **the ORM has none.**

`subsystem_map_check.py` and `package_index_check.py` are the two gates aimed at
the *documentation* rather than the code. The contract table is exact because a
checker enforces it; the map was prose, and prose rots. `doc_link_gate.py` proves
a referenced file *exists*; these prove a described package still *matches its
directory*.

`package_index_check.py` applies the same rule one level down, to the four
packages that document themselves per-module — `db/README.md`'s *Module map*,
`_monkeypatches/README.md`'s *Patch Index*, `http/README.md`'s *Module map*, and
`upgrade_code/README.md`'s *Module map* (whose rows are dated script stems such
as `18.1-00-sql-constraint`, not importable identifiers — the row pattern had to
stop assuming they were, or that inventory would have matched zero rows and
enforced nothing). Registration is not optional: `PACKAGE_INDEXES` is an inclusion list, so an
unregistered README would be gated by nothing — `test_every_core_readme_is_classified`
forces every core README into `PACKAGE_INDEXES` or into `READMES_WITHOUT_AN_INDEX`.
The check is scoped to the inventory **section**, because the READMEs carry other
tables that name `.py` files: `_monkeypatches`' *Recently Removed* table names
eight patches, six of which are modules that no longer exist (`urllib3`, `lxml`,
`xlrd`, `zeep`, `pytz`, `xlwt`; the other two rows retire a *patch* from a file
that is still there). An unscoped scan reports all six as failures against a
document that is exactly right — which is what `test_section_scoping_is_load_bearing`
pins, by name rather than by count. Scoping is the whole fix, and it has to be:
those names are backticked like every other path in the tree, so a gate that
reads a backticked path as an assertion cannot tell a citation from an assertion.
The only thing that can tell them apart is *where on the page they are*.

(`cross_repo_coherence.py` is a twenty-fifth checker and the only one outside CI: it
runs at the `pre-push` stage via `.pre-commit-config.yaml`, because GitHub checks
out this repo alone and the check needs the sibling checkouts to compare against.
It is opt-in per clone — `pre-commit install --hook-type pre-push`.)

Two further mechanisms keep the *non-structural* quality signals from
regressing:

- **Drift-zero count ratchet** (`tooling/ratchet/`, ADR-0006) — turns four tool
  counts into one-way contracts: **mypy, ruff, eslint, tsc, jsfunclen, jsprivate, jsserviceshape and naming** (floors in
  `tooling/ratchet/baselines/`). CI fails on any increase, and — in the default
  `exact` mode — on an *un-committed* decrease too, so every cleanup is locked
  in.

  ```bash
  python tooling/ratchet/test_ratchet.py     # self-test the tool
  python tooling/ratchet/ratchet.py --list    # current floors
  ```

- **DB-backed integration gate** (`.github/workflows/integration_tests.yml`,
  ADR-0007) — boots PostgreSQL 18 and runs two suites, **each against its own
  database**: `base` (less the excluded `TestReportsRendering` and
  `TestIrModelFieldsTranslation`) and `test_http`. So the decomposed pieces are
  verified to *behave*, not just to import cleanly.

### The limits of "enforced"

**The integration gate is the only lane that runs addon tests, and that is the
sharpest limit on the word "enforced" at the top of this page.** Every one of the
twenty-four boundary checkers is structural and DB-free: they read import graphs,
call graphs, reached-member sets and documents. A change can satisfy all
twenty-four, and Tier 1 and Tier 2, and still be wrong — renaming `OrmCore`'s
slots (`cache`/`engine` → `_cache`/`_engine`) broke two DB-backed addon tests in
2026-08 while every gate and both DB-free tiers stayed green, because nothing
those gates read had changed. Read a green boundary job as "the structure holds", never as "the
framework works".

The corollary is that a suite outside this lane is a suite nobody runs. When you
add a test addon, add it to the lane — **with its own database.** The suites
genuinely interfere: `test_http` depends on `mail`, whose `res_partner_views.xml`
inherits `base.view_res_partner_filter` anchored on `<filter name="inactive">`,
and base's `test_hard_reset_from_file_still_works` overwrites that view with a
minimal `<search>`. The write re-validates the children, so `-i base` is 5/5
green while `-i base,test_http` raises `ValidationError` — running only that one
test class. The base test is fragile by construction, since it mutates a shared
core view and therefore passes only while nothing inherits it; one database per
suite is what stops the next addon added here from tripping it.

ADR-0009 records how these gates were wired shut (mainline `push:` triggers,
full façade scope, re-measured floors) after an audit found each one bypassable.

## Known boundary exceptions

**None that are debt.** The two pinned rules both belong to
`core-does-not-depend-on-addons` and are deliberate, permanent, and scoped to
`odoo.service`: `service/_threaded.py` and `service/_worker.py` call
`IrCron._process_jobs` / `IrJob._process_jobs`, `@staticmethod` entry points that
open their own cursor because they run *before* a registry exists for the
database, so there is no `env` to route through. Both imports are deferred to
call time, and no override of either exists anywhere in
`odoo`/`enterprise`/`agromarin`. They are pinned rather than allow-listed so they
stay visible in every report.

The eight original contracts remain clean at zero; the exceptions surfaced by the
checker's first run have all been paid down:

- **Asset pipeline** (`esbuild`, `esm_bridges`, `esm_graph`, `esm_registry`)
  relocated from `libs/` to `odoo/tools/assets/` (ADR-0004). The dependency-free
  helpers it builds on (`asset_log`, `constants`) remain in `libs/`.
- **`libs/filesystem/osutil.py`** no longer imports `odoo.release`; the Windows
  service name is passed in by the caller (ADR-0004).
- **Layer-1 → Layer-2 deferred `BaseModel` imports** in `orm/domain/ast.py` and
  `orm/fields/relational/` (since split into a package: `_base`, `many2one`,
  `one2many`, `many2many`) replaced by the `orm/_recordset.py` injection seam.
  What remains of `BaseModel` in those modules is `if TYPE_CHECKING:`-guarded
  annotation, which never executes (ADR-0001).
- **`MODULE_UNINSTALL_FLAG`** moved from `addons/base/models/ir_model_common` to
  `orm/primitives` (the ORM's `unlink` branches on it, so the ORM owns it); it is
  re-exported from the addon for the `ir_model*` / `ir_module` code that sets it.
- **`format_number`, `intersperse`, `split`, `parse_grouping`** moved from
  `addons/base/models/res_lang` to `libs/locale/number_format`. They are pure and
  DB-free, and `tools/formatting.py` was reaching into an addon twice to call
  them. Locale data now arrives through a `LocaleConventions` **Protocol**, so
  `libs/` stays dependency-free while the addon's `LangData` satisfies it
  structurally.

## Appendix — how these rules were established

The blueprint above states the architecture as it is. This appendix records the
measurements that produced it, because several of the rules look arbitrary
without the finding that motivated them, and because each one is a worked example
of the failure mode this page is gated against: *a sentence that stayed true in
spirit while the code moved underneath it.*

**The bracketed tiers in `db/` and `http/` were documentation only** until they
were measured. Nothing verified the direction *between* the groups. Measured,
both were already layered — `db/` had 6 connectivity → resilience edges against 1
the other way (counting imported *symbols*, as `layer_check` does), `http/` 22
serving → features against 1 (counting import *statements*; by symbol it is 43
against 2) — and each back-edge was a module filed in the wrong bracket rather
than a genuine cycle. With `errors`/`dsn`/`utils` moved to `[foundation]` and
`helpers` to `[serving]`, both directions hold at zero and became contracts.

**The transitivity caveat is not hypothetical.** Two real modules spelling
`odoo/orm/fields` → `odoo.tools.something` → `odoo.orm.runtime` were added to the
tree and `--check` reported `New: 0` over the whole scanned core. (The figure
first written here — 6453 — was the *path* count of the day, before
`_collapse_nested` stopped overlapping `source` prefixes walking the same file
once per covering root; it was 6362 distinct files even then. Read the count off
a run, not off this line.)

**The mixin graph was called a DAG on the strength of the `self`-only view.**
Measuring recordset-mediated calls found `base.py` ⇄ `create` immediately;
extracting `_ConstraintsMixin` removed it, and both views are ratcheted now so
neither the prose nor the graph can move without the other. An earlier version of
the checker also silently collapsed the `read_group` subpackage into one unit,
hiding 10 edges and a whole 3-cycle — which is why its numbers are cross-checked
against the runtime `BaseModel.__mro__`.

**`orm/__init__.py`'s docstring and the gate once disagreed.** The docstring
omitted `components/` and `_recordset.py` and filed `_typing.py` under
"cross-cutting", where `layer_check.py` scopes it to Layer 0. A reader who opened
the package instead of the page got a different architecture.

**`core-does-not-depend-on-addons` first reported eight tolerated edges, not
four.** `_ImportCollector` emits both `<base>` and `<base>.<name>` for every
`from X import Y`, so each of the four statements was reported twice. The
synthesised record is now kept only when it is the one that carries the violation
(`from odoo import models` under a contract that forbids `odoo.models` but not
`odoo`), so one import statement is one violation.

**The `env` surface figures were copied, not measured.** This page and
`env_surface_check.py`'s own docstring both said `orm/fields` reaches *5*
unsanctioned private `Environment` members. Five is the size of the
distinct private set across the whole ORM — `_field_depends_context` is reached
from both packages — not `orm/fields`' share of it. Both prose copies agreed with
each other and neither agreed with the checker. Every measured figure on this
page is now derived from a live run of the checker that produces it.

**Both seam gates scoped Layer 2 to `orm/models` alone**, which left eight
top-level `odoo/orm/*.py` modules in **no** scope at all — including
`registration.py`, which was reading three private `Registry` attributes on every
model setup while `orm-helpers-and-registration-stay-below-runtime` reported it
clean at zero. Correctly so: it imports `odoo.orm.runtime` nowhere. That is
exactly the channel those gates exist to watch, and it ran through the one file
neither of them read. Hence `_orm_layer_scope.py` and its completeness test.

**`env_model_surface_check.py`'s subtree pins exist because the flat set is not
enough.** Appending `env["ir.model"]` to `orm/components/model_graph.py` — a
package whose entire contract is that it is pure Python — passed `layer_check`,
`env_surface_check`, `pool_surface_check` and the model-set gate at once.

**`py_cycle_check.py` reported on 323 modules and called that the core.** It is
338: `odoo/tests/` is the shipped test *framework*, and a "drop any path with a
`tests` component" filter removed all 17 of its modules. `layer_check` had the
identical bug and fixed it at `_CORE_TEST_FRAMEWORK_PACKAGE`; nothing had
propagated the rule.

**`libs_facade_check.py`'s scope has widened twice on measurement.**
`odoo/tools` held 19 leaf imports and `orm`/`http`/`modules`/`service` nine more,
all while the gate reported green, because a tree outside the scope cannot fail.
It scans every core package now (`odoo/libs` itself excepted: an area importing
its own leaves is how a package is built), and `test_every_core_package_is_scanned`
fails if a new one is added without being scanned or explicitly excused. It is a
separate tool rather than a `layer_check` contract because `Contract.allow` is
prefix-matched and `_ImportCollector` emits a synthetic `<base>.<name>` per
imported symbol, so `odoo.libs.numbers.float_round` (a symbol) is
indistinguishable *by name* from `odoo.libs.numbers.float_utils` (a module); the
discriminator is on disk.

**The subsystem map depicted four directories that do not exist.** It drew
"connectivity"/"resilience" under `db/` and "core"/"features" under `http/` as
subdirectories when both packages are flat, and the invented "core" node masked
the real, undocumented `http/core.py`. That is what `subsystem_map_check.py` was
written for.

**The HTTP call graph was cited after it had been deleted.** It lived in
`odoo/http/__init__.py`'s module docstring; `4ffeacacd8c` stripped docstrings
from `odoo/` and, because nothing read that one, took the only detailed copy with
it while this page went on calling itself the abridged version. Recovered from
`4ffeacacd8c~1`, re-verified symbol by symbol, and moved to a README so the strip
policy and the call graph no longer compete for the same lines.

**`env._core` handed out the object it claimed to curate.** `OrmCore`'s slots
were named `cache`/`engine`, so `env._core.cache` *was* `transaction._cache_store`
while this page said the raw objects stay private to `Transaction`. Renaming them
to `_cache`/`_engine` is also the change that broke two DB-backed addon tests
with every structural gate green — the worked example under *The limits of
"enforced"*.

**`test_http` was in no workflow at all** and had accumulated three defects, one
of them a test committed red two months earlier. It is in the integration lane
now, with its own database.

**An earlier version of the `package_index_check.py` paragraph claimed the
removed patch names were "quoted rather than backticked on purpose".** They never
were, and no convention asks authors to punctuate around a checker. Section
scoping is the fix.

See also: `doc/adr/` (architecture decisions, 0001–0013 — 0012/0013 cover
attachment storage and content placement, which sit above this page's scope) and
the `orm/__init__.py` module docstring.
