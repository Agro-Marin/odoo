# Module view — what exists, and who may depend on whom

> One of the views indexed by [`ARCHITECTURE.md`](ARCHITECTURE.md).
> This view answers *where does code live and what may it import*. For *what runs
> when*, see [`runtime.md`](runtime.md); for the checkers that hold these rules
> shut, [`gates.md`](gates.md); for how they were arrived at,
> [`findings.md`](findings.md).

This is the view the CI gates are built around, and the most mechanically
verified thing in the repository: the map below is checked against the tree, and
every contract in the table is a program that runs on each push.

## Subsystem map

```
odoo/
├── orm/            The ORM, as an explicit 4-layer architecture (see below)
│   ├── primitives, parsing, validation, constants, _typing   (Layer 0)
│   ├── fields/, domain/                                       (Layer 1)
│   ├── models/  (BaseModel + 26 mixins, metaclass)            (Layer 2)
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
│   │               core (the `request` proxy + its LocalStack), helpers,
│   │               _retry (the RetryParticipant handed to service/transaction)
│   └── [features]  openapi (OpenAPI 3.1 from the routing map),
│                   _params (annotation-driven @route(typed=True) coercion),
│                   geoip, constants, exceptions, _protocols
├── service/        Process lifecycle + the servers
│   ├── server, _base_server, _threaded (ThreadedServer + EventServer),
│   │   _prefork, _worker, _watcher, wsgi, _cron, lifecycle
│   ├── db/         Database management, the /web/database/manager service
│   │               (ADR-0014). Reads downward:
│   │               rpc -> {restore -> {lifecycle, listing}, dump -> listing,
│   │                       lifecycle -> listing}
│   └── transaction (the retrying() primitive), model, security, common,
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

### `tools/` has a third role: it is the façade for part of `libs/`

The split above says `libs/` is Odoo-agnostic and `tools/` is Odoo-coupled. In
practice `tools/__init__.py` also re-exports **23 of its 101 `__all__` symbols
straight from `odoo.libs`** — `SQL`, `float_round`, `float_compare`,
`classproperty`, `lazy`, `parse_version`, `SetDefinitions`, `pg_varchar`,
`make_index_name` and 14 more.

This is deliberate (`libs_facade_check.py` polices *how* `libs` is imported, so
a re-export layer is the sanctioned door) but it was written down nowhere, and
it has one real cost: at the point of use, `from odoo.tools import float_round`
and `from odoo.tools import config` are indistinguishable, though one is a pure
function and the other reaches the whole runtime. The distinction the
`libs`/`tools` split exists to express is erased by the façade that publishes
it.

**The rule that follows:** addon code may keep using `odoo.tools` for either
kind. **Core code should import from the owning package** — `odoo.libs.sql`,
not `odoo.tools`, for `SQL` — so that a module's imports state which layer it
actually depends on. That is not cosmetic: Layer 0 of the ORM reached for
`odoo.tools` solely because it was the advertised door to `SQL`, and taking it
from `odoo.libs.sql` instead is what allowed `orm-layer0-is-foundational` to be
tightened (see the Layer 0 bullet under *The ORM layer model*).

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
  `_compute_engine`). **`env.cache` is the recordset-level cache API** — not a
  legacy wrapper over `_core`, which is what this page called it until
  2026-08-08. The two are different abstraction levels and both are sanctioned:
  `OrmCore.get_value(field, record_id)` takes a raw id, while
  `Cache.get_values(records, field)` takes a *recordset* and resolves the field
  cache through its `env`, so the caller never has to know that a
  context-dependent field is stored `{cache_key: {id: value}}` rather than
  `{id: value}`, or that a term-translated one is reached through a
  `LangProxyDict`. That is exactly why ADR-0010 **dropped** its own step 4
  (retire `env.cache`) on reassessment: the migration target was wrong, and a
  mechanical rewrite onto `_core` would have mishandled those layouts and
  coupled addon code to private field helpers. The label here was inherited from
  the ADR's *Context* section, written before that reassessment; its
  *Implementation status* says the opposite, and the code agrees with the
  Implementation status.
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
| `transaction-primitive-is-transport-agnostic` | `odoo/service/transaction.py` must not import `odoo.http` — the transport injects a `RetryParticipant` instead (ADR-0003's seam shape) | ✅ clean |
| `root-modules-are-foundational` | `odoo/exceptions.py` & `odoo/release.py` must not import `odoo.*` except `odoo.libs` (ADR-0016). **Not** `logutils.py`, which imports `db`/`tools` and is a consumer of the stack | ✅ clean |

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

`layer_check.py` reasons about **import** edges. `BaseModel` is composed from 26
`__slots__ = ()` mixins by multiple inheritance — 18 public (`CreateMixin` …
`AccessMixin`) plus 8 private (`_PropertiesMixin`, `_QueryMixin`,
`_ConstraintsMixin`, `_DisplayNameMixin`, `_FieldComputeMixin`, `_HooksMixin`,
`_MagicFieldsMixin`, `_ModelMetadataMixin`) — and they
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
`create`**, where `base.py` called `self.create(…)` in `name_create` while
`create.py` called `_validate_fields` on recordsets `self` never names.
(No line citation: `name_create` has since moved to `_DisplayNameMixin`, and a
pinned line number in a file that shrank by 87 lines is how
`test_line_number_citations_resolve` earns its keep.)

It was broken the same way its predecessors were, by moving behaviour off the
composition root: `_constraint_methods` and `_validate_fields` live on a
`_ConstraintsMixin` leaf (`mixins/_constraints.py`), so `create` and `write`
reach the constraint machinery without touching `base.py`. **A leaf that nothing
in the composition depends on cannot close a cycle** — that is the design rule
for new mixins.

**`base.py` is now a root with no edges at all**, which is what that rule was
aimed at and what this page and the checker both previously claimed while it was
not true. It kept six members after the metadata split, and measured through the
checker's own collector they gave it out-edges to `create` (`name_create`'s
`self.create(…)`), `_metadata`, `traversal` and `_magic_fields`, and — the part
that settles it — **in-edges from `lifecycle` and `unlink`**, each reaching it
for one thing: the `_onchange_methods` / `_ondelete_methods` registries. A
composition root that two units depend on is a participant.

Three more leaves finished it. `_HooksMixin` (`mixins/_hooks.py`) takes the two
registries, joining `_constraint_methods` as the third `own_class_memo`
decorator scan — `helpers.ORM_CLASS_MEMOS` lists all three memo keys side by
side, while their owners had been split across three files.
`_DisplayNameMixin` takes `_compute_display_name`, `_rec_name_fallback` and
`name_create` — `orm/models/mixins/_display_name.py:51` calls `self.create(…)`,
which is the same edge as before, now travelling with the behaviour that needs
it instead of sitting at the root.
`_FieldComputeMixin` (`mixins/_field_compute.py`) takes `_compute_field_value`,
whose only caller is Layer 1 (`Field.compute_value`).

That last one is a worked example of the design rule. The obvious home was
`RecomputeMixin` — and it is wrong: `traversal` already reaches `recompute`
through `flush_model`, so `_compute_field_value`'s `self.filtered("id")` added
`recompute → traversal` and made a 2-cycle. The gate reported it on the first
run. On its own leaf, which nothing in the composition depends on, the same
three dependencies (`traversal`, `_constraints`, `_metadata`) close nothing.

`base.py` now holds `__slots__`, `_register`, two setup hooks, `get_base_url`,
the deprecated `_cr`, and the three registration calls — in-degree 0, out-degree
0, in both views.

Both views are ratcheted at zero (`recordset_max_scc` 1,
`recordset_cyclic_edges` 0, `recordset_scc_without_base` 1), so a cycle spelled
through a recordset fails CI even though the `self`-only numbers would stay
clean.

The checker's numbers are cross-checked against the runtime
`BaseModel.__mro__`, not just against themselves. It counts *file-level*
units — 31, since `read_group/` contributes five (`_empty`, `fill`, `format`,
`mixin`, `sql`) and `base.py` is itself a unit — not the 26 bases.

```bash
python tooling/architecture/mixin_coupling_check.py            # report
python tooling/architecture/mixin_coupling_check.py --check    # CI
python tooling/architecture/mixin_coupling_check.py --explain search read
python tooling/architecture/mixin_coupling_check.py --composition Field \
    --explain _field_convert base.py
```

**`BaseModel` is not the only composition, and the gate now measures all five —
three in the ORM, two outside it.**
`Field` is `Field(_FieldDescriptionMixin, _FieldConvertMixin, _FieldSqlMixin)`
over a `_FieldStubs` typing declaration and `Registry` is
`Registry(_RegistryFieldsMixin, _RegistrySchemaMixin, …)` over a
`_RegistryStubs` one — the same construction, equally invisible to
`layer_check`. `Field` was measured by nothing until 2026-08-08 while being 1401
lines against 628 in its three mixins, the inverse of the ratio `models/`
reached; `Registry` until 2026-08-09, at 1018 lines against 461 in its two, a
worse ratio still. Each composition carries its own floors and a drift in any of
them fails.

**Each generalisation found the new composition to be the worst of the set.**
`Field`'s first run found a 2-cycle (below). `Registry`'s first run found a
**3-unit cycle over 4 edges — every unit in one component**, the only one of the
three that was not a DAG: `registry.py` reached `_registry_fields`
(`_ensure_field_triggers`, `field_depends`, `field_depends_context`) and
`_registry_schema` (`check_foreign_keys`, `check_indexes`, `check_tables_exist`),
while both reached back into the root for `models`, and `_registry_schema` for
`init_phase` as well. `scc_without_base` was already 1, which named the cause:
every back-edge landed on the composition **root**.

It was broken the way its two predecessors were — by moving the clusters the
mixins reach for off the root onto leaves that reach nothing back.
`_RegistryModelsMixin` (`orm/runtime/_registry_models.py`) takes the `models`
container and the `Mapping` protocol over it; `_RegistryInitPhaseMixin`
(`_registry_init_phase.py`) takes the `init_models()` window accessor.
`cyclic_edges` 4 → 0, `max_scc` 3 → 1.

**That was half the job, and the first write-up of it was wrong.** `cyclic_edges`
records an edge only where the reached member is bound in some unit's **class
body**; state assigned in a constructor and declared only in the typing stub is
read by everyone, owned by nobody, and produces no edge — the stub is excluded
from being a unit precisely so it cannot absorb them. Two consequences, both
measured 2026-08-09:

- **It hid coupling.** Eight `Registry` members were assigned in `Registry.init`
  and read by `_registry_schema` / `_registry_fields` — `_constraint_queue`,
  `_ordinary_tables`, `field_setup_dependents`, `has_trigram`, `has_unaccent`,
  `model_graph`, `not_null_fields`, `unaccent`. Attributed to the unit that
  *assigns* them, the composition was **still a 3-unit SCC after the extraction
  above**.
- **A declaration could switch the gate off.** Deleting the one line
  `models: dict[str, type[BaseModel]]` from `Registry`'s class body — no
  behaviour change, the attribute still assigned in `init`, still read by both
  mixins — took `cyclic_edges` from 4 to 2 on the pre-split tree.

So the gate carries a fourth ratcheted number, `unowned_shared_state`: members
read by two or more units that no unit owns. The two move in opposite
directions, so hiding an edge fails the ratchet twice.

**All eight then got real owners.** Each is now declared *and* initialised by the
mixin whose concern it is, called from `Registry.init` through one
`_init_*_state()` hook each; the unaccent/trigram cluster went to a new
`_RegistryCapabilitiesMixin` (`orm/runtime/_registry_capabilities.py`) because a
database *capability* is not a schema fact — `check_indexes` is one consumer and
the domain optimiser's `pool.unaccent` is another. Inter-unit edges rose 7 → 9,
because the coupling became **visible**, and `unowned_shared_state` fell 8 → 0.

**`Registry` is now a DAG under the assignment-site model as well as this gate's**
— the property the first round claimed and did not have. The other two are
unchanged and still carry theirs: **BaseModel 4** (`env`, `_ids`,
`_prefetch_ids`, `_log_access` — the recordset's own identity, assigned by
`IterationMixin.__init__`) and **Field 1** (`description_attrs`). Read the pair,
never `cyclic_edges` alone. Under assignment-site ownership `BaseModel` still
shows a 2-cycle, `_metadata` ⇄ `iteration`; that one is open.

The move that mattered was the *declaration*, not the methods: a unit owns what
its **class body** binds, so `models` had to leave `Registry`'s body for the
leaf's. Moving the methods alone left `cyclic_edges` at 6 — worse than the
original 4, because the new leaf then reached the root for the container it was
supposed to own.

**The gate has now been blind twice, and that is itself the finding.** Both
misses were caught by someone recognising the construction by eye, which is not
a gate. `test_mixin_coupling_check.py` therefore discovers composition roots
from the tree — a class in `odoo/orm` with two or more `*Mixin` bases whose own
name does not end in `Mixin` — and fails if one is absent from `COMPOSITIONS`.
It finds exactly `BaseModel`, `Field` and `Registry`; `ReadGroupMixin` is three
mixins wide but is a *unit* of `BaseModel`, which is what the name test
excludes.

**Two more compositions live outside `odoo/orm`, and they are gated now too.**
`Request(_RequestServeMixin, _RequestResponseMixin, _RequestCsrfMixin)` over
`RequestState` (`http/request_class.py`) and `Cursor(_BulkAccessMixin,
_MetricsMixin, BaseCursor)` (`db/cursor.py`). They were recorded here as
out-of-scope on the day the gate was generalised to `Registry`, which was the
wrong call: **`Cursor` had a 2-cycle in it.**

`cursor.py` reached `_MetricsMixin` for `_format` / `_record_metrics` /
`_record_sql_log` / `print_log`, and the mixin reached back for `sql_from_log`,
`sql_into_log` and `sql_log_count` — the three counters it exists to maintain,
declared on `Cursor`. `metrics.py` carried the proof in its own source: a
`_MetricsHost` Protocol under `TYPE_CHECKING` naming exactly those three. **A
declaration of what a mixin reaches back for is a declaration that the state has
no owner** — the same tell `_RegistryStubs` was. The counters moved onto
`_MetricsMixin` behind an `_init_metrics_state()` hook; `cyclic_edges` 2 → 0,
and the Protocol is down to `_thread`.

Two filter changes were needed to see it, both neutral for the existing three
(verified by measuring all of them across the change): `_is_composed_class` now
also matches a class by its **own** `*Mixin` name, because `db/`'s two mixins
are bare classes with no stub to inherit; and `collect_units` skips `tests`
packages, because `db/` and `http/` carry test doubles that inherit the real
mixins (`_FakeRequest`, `_FractionOnly`, `_MetricsCursor`) and would enter the
graph as units.

`Request` was the only one of the five that was a DAG on first measurement — one
inter-unit edge, `_serve` → `request_class.py`. Its `unowned_shared_state` is 8
(`app`, `db`, `dispatcher`, `env`, `httprequest`, `params`, `registry`,
`session`: the request's identity, declared on `RequestState`), and `Cursor`'s is
5 (`_cnx`, `_obj`, `_thread`, `_schema_cache`, `_before_statement`).

**The score across five compositions: four were tangled the first time anything
looked, and each was found by a person, not a gate.** That is what
`test_mixin_coupling_check`'s discovery test now exists to end — and its own
scope was `odoo/orm` until `Cursor` showed why a coverage list narrower than the
thing it guards reproduces the bug it exists to catch.

The first run found what the absence of a gate had allowed: a 2-cycle,
`_field_convert` ⇄ `base.py`. `base.py` reached conversion from the descriptor
protocol (`convert_to_cache` / `convert_to_record` / `convert_to_write`) and
conversion reached back for *declared attributes* (`column_type`,
`company_dependent`, `translate`, `_is_context_dependent`,
`_company_dependent_fallback_raw`) — it had been there, unmeasured, for as long
as the split existed.

It was the shape `BaseModel` had before 2026-08a, and it was broken the same
way: by moving the declarations off the composition root. `_FieldMetadataMixin`
(`fields/_field_metadata.py`) holds the **column-shape** cluster — what a field
*is*, as a column, and what derives from that — so conversion, SQL generation
and description can ask that question without reaching the root.
`cyclic_edges` 2 → 0, `max_scc` 2 → 1. **Both ORM compositions are now DAGs**,
and both gates forbid a cycle rather than bounding one.

The leaf is deliberately the column shape rather than all ~40 of `Field`'s
declared attributes: that cluster is what conversion, SQL and description
actually ask for, and it is the only one whose removal moves the graph. Widening
it further would be a larger move with no gate movement to show for it.

For `Field` the units are the mixin composition only. Concrete field types are
*subclasses*, and they override base methods freely — `BaseString` overrides six
of `Field`'s twelve cache methods — but that is the override surface, a
different graph.

The mixin call graph is the largest such surface but not the only one. What
follows carries coupling no import edge records either — and the first of it
inverts the layering this view has just described.

**Layers 1 and 2 reach the runtime through `self.env` and `self.pool`, not
through imports — and Layer 1 reaches harder.** The direction contracts
`orm-layer1-below-models-and-runtime` and `orm-models-below-runtime` are clean
and always will be, because that reach produces no import edge at all.
Measured, Layer 1 (`orm/fields`) is the heavier consumer on both channels: it
is wider into `Environment`'s privates than Layer 2 (4 unsanctioned private
members against 2, 10 accesses against 3); **it touches the Registry at 30
sites against `orm/models`' 28**, and uses 5 `pool[<model>]` subscripts against
Layer 2's 3. Be precise about the rest, because the inversion is one of volume
and not of kind: Layer 2 reaches *more distinct* members than Layer 1 (15
against 9), and has private reaches of its own — `_ensure_field_triggers`,
`_init_modules`, `_database_translated_fields`,
`_database_company_dependent_fields`. **So the
layering story is true of the import graph and false of the runtime graph.** A
reader who takes the contracts above as the whole picture will predict the wrong
blast radius for a change to `Environment` or `Registry`. Pinned by
`env_surface_check.py` and `pool_surface_check.py`; both draw their layer scope
from the shared `tooling/architecture/_orm_layer_scope.py`, so the two cannot
drift apart.

**Four runtime members existed only inside a single call, and Layer 1 mutated
one of them.** Until 2026-08-09 `Registry` created `_post_init_queue`,
`_foreign_keys`, `_relation_reflections` and `_is_install` inside `init_models`'
`try:` and `del`-eted them in its `finally:`, so they existed only for the
duration of that call — and `fields/relational/many2many.py` wrote to the third
from Layer 1, which worked solely because `update_db` runs inside that window.
Nothing declared the ordering, and nothing but an `AttributeError` during module
installation would have caught a violation. This page documented one of the
four; `pool_surface_check.py` pinned that one as a known violation, and the
other three were reached only through public methods, which is what made them
look unremarkable.

They are now one `InitModelsPhase` (`orm/runtime/_init_phase.py`) behind
`Registry.init_phase`, a property that raises a `RuntimeError` naming the window
when it is closed, and Layer 1 calls `pool.add_relation_reflection(...)`. The
lifetime is one nullable attribute that can be declared, so
`orm/runtime/_registry_stubs.py` — the `if TYPE_CHECKING:`-only class that
existed partly to give those attributes a definition site — no longer carries
them. See [`risks.md`](risks.md) R1, the register's first closed entry.

**The temporal-coupling shape itself is not gone**, which is the part worth
keeping: `registration.py` still reads `Registry._init_modules` for the same
reason (model setup asking whether an install is in flight), pinned in
`pool_surface_check.py` with the same remediation — a public predicate.

**The set of addon-owned models the framework may name is closed.** The
framework's largest real coupling to its consumer produces no import edge
either, because it is spelled as a string (`env["res.users"]`, see *Models are
assembled per database* in
[`ARCHITECTURE.md`](ARCHITECTURE.md)).
`env_model_surface_check.py` ratchets *which* models are reached, as an exact
set, and pins seven subtrees at zero reaches — `orm/components`, `libs`, `db`,
the `api`/`fields`/`models` shims, `_monkeypatches` — each of which already
claims that property for an independent reason, so a first reach there is a
contradiction rather than a cost.

**Direction rules are blind to cycles.** Every edge of a cycle can sit inside
one layer and cross no boundary, so the contracts above cannot see one. Python
hides this better than ESM, which is what lets it accumulate: a
partially-initialised module is a live object, so a cycle usually *works* until
an entry point changes. `py_cycle_check.py` reconstructs the import graph to
find them. Four are pinned (`service`, `modules`, `cli`, `tests` — all the
benign package↔submodule shape); **the ORM has none.** Function-local imports
are deliberately not counted as edges, since a deferred import is the
sanctioned way to break a cycle.

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
  `search`/`unlink`) dispatch row I/O through `env.backend`, which is
  **non-optional** and has two implementors: `PostgresBackend` adapts the port to
  the model's own `_*_sql` methods and `runtime/backend.py::InMemoryBackend`
  adapts it to `DictBackend` (ADR-0011 and its 2026-08-08 amendment). Production
  CRUD no longer sniffs the test backend via `transaction.storage`, and since
  2026-08-08 it does not sniff it via a null check either. Until then `env.backend is None` *was*
  the PostgreSQL implementation — an unnamed branch at fifteen sites across nine
  files, which meant the Protocol described only the test double and a
  differential suite had one object to compare against. Three sites still branch,
  on declared capabilities rather than a null check, because there the two
  backends run different algorithms rather than two implementations of one; the
  sharpest is `Many2many.read`, where the SQL path fuses a JOIN into the comodel's
  `Query` and the port's signature has nowhere to put it.
- **Framework ↔ addon-owned models:** the core reaches application models by
  string key (`env["res.users"]`), never by import. That is deliberate, and it is
  the one seam with no import edge at all, so it has its own gate — see
  `env_model_surface_check.py` below.

