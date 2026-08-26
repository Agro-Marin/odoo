# Module view — what exists, and who may depend on whom

> One of the views indexed by [`ARCHITECTURE.md`](ARCHITECTURE.md).
> This view answers *where does code live and what may it import*. For *what runs
> when*, see [`runtime.md`](runtime.md); for the checkers that hold these rules
> shut, [`gates.md`](gates.md); for why a given rule exists, `doc/adr/` and the
> gate's own module docstring.

The map below is checked against the tree; every contract in the table is a
program that runs on each push.

## Subsystem map

```
odoo/
├── orm/            The ORM, as an explicit 4-layer architecture (see below)
│   ├── primitives, parsing, validation, constants, _typing,
│   │   _protocols                                            (Layer 0)
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
│       _dispatch (one arity policy for the common/db RPC tables),
│       _env, _helpers, _db_helpers, _dump_scanner, _metrics
├── modules/        The module graph (iterated by phase, dependency depth,
│   │               then name) and what loads it
│   └── module_graph, module, loading, migration, db, neutralize,
│       _protocols (what a loader needs of a cursor, narrower than one),
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
> the table below. Filing a module in the right bracket is a decision, not a
> caption: `db/errors.py` (with `dsn`/`utils`) imports nothing else in `db/` and
> is used by both tiers, so it is `[foundation]`, not `[connectivity]`;
> `http/helpers.py` imports `core` and is imported by
> `dispatcher`/`_serve`/`request_class`, so it is `[serving]`, not `[features]`.

Both tiers were documentation only until they were measured, and both turned out
already layered. Each back-edge was a module filed in the wrong bracket, not a
genuine cycle. Moving `errors`/`dsn`/`utils` to `[foundation]` and `helpers` to
`[serving]` took both directions to zero, which is what made them contracts.

| Tier pair | Downward | Back-edges | Convention |
|---|---:|---:|---|
| `db/` `[connectivity]` → `[resilience]` | had 6 connectivity → resilience edges | 1 | counting imported *symbols*, as `layer_check` does |
| `http/` `[serving]` → `[features]` | 22 serving → features | 1 | counting import *statements*; by symbol it is 43 against 2 |

**These are the pre-fix figures**, re-derived by
`TestEdgeCountConventions`, which holds the *old* bracket assignment
(`errors`/`dsn`/`utils` in `[connectivity]`) for exactly that reason. Correcting
its map to match the one above would change all four numbers and measure a
different claim.

Three things a re-measurement has to hold apart, each of which produces a
plausible wrong answer on its own:

- **Statements against symbols.** `layer_check` counts symbols; `from .reaper
  import IdlePoolReaper, note_activity` is one statement and two. Pick the other
  convention and the two rows read 5 and 44.
- **`from . import x`.** A relative import with no module names its targets in
  `node.names`, not in `node.module`. Skip that form and `db/`'s back-edge
  disappears, leaving the tier looking cleaner than it was.
- **Runtime against typing.** `http/_protocols.py` is `[features]` and names
  `Dispatcher`, `Session`, `FutureResponse`, `HTTPRequest` and `Response` from
  `[serving]` — upward, and legal, because all five are inside
  `if TYPE_CHECKING:` and never execute. `http-features-below-serving` is
  correctly clean; a probe that reads import statements without honouring the
  guard reports five violations against a tier that has none.

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
before anything else (see **Process boot**) and patches third-party modules only.

### `tools/` has a third role: it is the façade for part of `libs/`

`tools/__init__.py` re-exports **22 of its 102 `__all__` symbols straight from
`odoo.libs`** — `SQL`, `float_round`, `float_compare`, `classproperty`, `lazy`,
`parse_version`, `SetDefinitions`, `pg_varchar`, `make_index_name` and 13 more.
Sanctioned: `libs_facade_check.py` polices *how* `libs` is imported, and a
re-export layer is the door it sanctions.

Cost: at the point of use `from odoo.tools import float_round` and `from
odoo.tools import config` are indistinguishable, though one is a pure function
and the other reaches the whole runtime. The façade erases the distinction the
split exists to express.

**22 understates the exposure, because it counts one file's import statements.**
Following each exported symbol one hop further — into the `tools` submodule that
supplies it — **59 of the 102 come from `odoo.libs`**, the other 43 arriving
from `tools`' own modules: 22 imported by `tools/__init__.py` itself and 37
through submodules that re-export from `libs` in turn. So the erasure covers
more than half the façade, not a fifth of it, and no reading of
`tools/__init__.py` alone shows that.

**Resolve by *import*, not by `__module__`.** Two of the 59 (`html_escape`,
`single_email_re`) report `markupsafe` and `re` at run time, being a re-exported
third-party alias and a compiled pattern rather than functions `libs` defines. A
live-attribute sweep therefore answers 57 and looks authoritative doing it.

| Caller | Import | Why |
|---|---|---|
| addon code | `odoo.tools`, either kind | the façade is the published surface |
| core code | the owning package — `odoo.libs.sql`, not `odoo.tools`, for `SQL` | a module's imports must state which layer it depends on |

Not cosmetic: ORM Layer 0 reached for `odoo.tools` only because it was the
advertised door to `SQL`. Taking it from `odoo.libs.sql` is what let
`orm-layer0-is-foundational` be tightened.

### Public import surface

Addon code imports **`odoo.api`, `odoo.fields`, `odoo.models`** — never
`odoo.orm.*`. Each is an `__init__.py` re-export shim with an explicit
`__all__`, which is what lets the ORM's internal layout move without breaking
addon imports. `facade-boundary` fails CI on any runtime `odoo.orm.*` import
under either addon tree (`if TYPE_CHECKING:` exempt). ADR-0008.

| Tree | Module name | Note |
|---|---|---|
| `odoo/addons/` | `odoo.addons.*` | `base` plus the `test_*` suites |
| repo-root `addons/` | `addons.*` | mounted at `odoo.addons.*` by the addons-path loader at run time |

## The ORM layer model

The ORM is organised as strict layers; **runtime imports point downward only.**
Cross-layer references for *typing* are allowed when guarded by
`if TYPE_CHECKING:` (they never execute), which is how the layers share types
without forming import cycles.

```
Layer 3  runtime/      Environment, Registry, Transaction        ─┐ imports
Layer 2  models/       BaseModel, mixins, metaclass, table objs   │ downward
Layer 1  fields/ domain/   Field types, domain AST + optimizer    │ only
Layer 0  primitives parsing validation constants _typing _protocols ─┘

         components/   FieldCache · ComputeEngine · UnitOfWork · ModelGraph
                       Beside the stack, not under it: Layers 2 and 3 import
                       it, Layers 0 and 1 never do. Pure Python — no odoo
                       imports at runtime except odoo.libs. Collaborators
                       injected.
```

| Layer | May import | Notes |
|---|---|---|
| **0** `primitives` `parsing` `validation` `constants` `_typing` `_protocols` | no higher *ORM* layer | Forbidden set is `orm.fields`, `orm.domain`, `orm.models`, `orm.runtime`, `orm.components` **and** the façades `odoo.fields`/`odoo.models`/`odoo.api` — a re-export shim is the obvious way round a rule written only against `odoo.orm.*` |
| **1** `fields/` `domain/` | Layer 0 | Imports `components/` nowhere |
| **2** `models/` | Layers 0–1, `components/` | `mixins/recompute.py` → `components.recompute.RecomputeScheduler` |
| **3** `runtime/` | Layers 0–2, `components/` | Owns the instances: `Transaction` constructs `FieldCache`, `ComputeEngine`, `UnitOfWork`, `OrmCore` |

The invariant at every layer is "nothing from the ORM above it", not "nothing
from `odoo`": all four import `odoo.tools`, `odoo.libs` and `odoo.exceptions`
freely.

**Layer 0's permissions are wider than its practice**, and the pairing must not
be read as a dependency claim. It may use `odoo.tools` and `odoo_rust`; it
exercises only the first — `primitives.py` takes the `SQL` builder from
`odoo.tools`, and **no Layer-0 module imports `odoo_rust` at all**. The extension
enters the ORM at `helpers.py`, `models/mixins/read.py` and
`runtime/environment.py`.

### `components/` — the two cache APIs

The cache/compute/unit-of-work engine. Pure Python apart from `odoo.libs`
(`model_graph.py` imports `Collector`), collaborators injected (ADR-0002).

Two cache APIs, at different abstraction levels. **Both are sanctioned.**

| API | Key | Reached as | Owner |
|---|---|---|---|
| `OrmCore.get_value(field, record_id)` | raw id | `env._core` (`components/core.py`) | curated façade over the raw objects |
| `Cache.get_values(records, field)` | *recordset* | `env.cache` | resolves the field cache through the recordset's `env` |

`env.cache` is **not** a legacy wrapper over `_core`. It is what saves a caller
from knowing that a context-dependent field is stored `{cache_key: {id: value}}`
rather than `{id: value}`, or that a term-translated one is reached through a
`LangProxyDict`. ADR-0010 **dropped** its own step 4 (retire `env.cache`) for
that reason: a mechanical rewrite onto `_core` would have mishandled those
layouts and coupled addon code to private field helpers. Where the ADR's
*Context* and its *Implementation status* disagree, the code agrees with the
Implementation status.

The raw objects stay private to `Transaction` (`_cache_store`,
`_compute_engine`).

> **"Pure" is a direction claim, not an isolation claim.** The contract is about
> this package's imports and it holds. A component still cannot be imported
> alone: `import odoo.orm.components.model_graph` executes the parent package,
> and `orm/__init__.py`'s last line is `import odoo.init` — the bootstrap, which
> applies `_monkeypatches` and so loads `babel` (and `lxml` through it). Hence
> `components/tests/conftest.py` stubs the `odoo` / `odoo.orm` /
> `odoo.orm.components` namespace packages instead of importing them. Read
> "unit-testable" as "needs no ORM runtime objects", not "costs nothing to
> import".

`orm/__init__.py`'s docstring states the same layer model member by member.
Where a doc and the gate differ, `layer_check.py`'s `CONTRACTS` wins — it is the
definition that runs.

## Enforced dependency rules

| Contract | Rule | Status |
|----------|------|--------|
| `libs-is-dependency-free` | `odoo/libs/**` must not import `odoo.*` (except `odoo.libs`) | ✅ clean |
| `db-is-orm-agnostic` | `odoo/db/**` must not import `odoo.orm/models/fields/api` | ✅ clean |
| `tools-does-not-reach-the-orm-runtime` | `odoo/tools/**` must not import `odoo.orm.runtime` (Layers 0–1 stay allowed) | ✅ clean |
| `orm-helpers-and-registration-stay-below-runtime` | `orm/helpers.py` & `orm/registration.py` must not import `orm/runtime` | ✅ clean |
| `orm-components-are-pure-python` | `odoo/orm/components/**` must not import `odoo.*` (except `odoo.libs`) | ✅ clean |
| `orm-layer0-is-foundational` | Layer-0 (`primitives`, `parsing`, `validation`, `constants`, `_typing`, `_protocols`) imports no higher ORM layer | ✅ clean |
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

| Caveat | Detail |
|---|---|
| **Every contract is a DIRECT-edge rule, never transitive** | `orm-layer1-below-models-and-runtime` stops `odoo/orm/fields` importing `odoo.orm.runtime`; it says nothing about `odoo/orm/fields` → `odoo.tools.something` → `odoo.orm.runtime`. Transitivity is deliberately not the fix: `tools/` is the Odoo-coupled utility layer, so transitively everything reaches everything through it and the rule would need a large, low-signal baseline. The narrower invariant holds at zero — `tools-does-not-reach-the-orm-runtime`. Add a targeted contract when a conduit matters |
| **Test files are not scanned — but `odoo/tests/` is not test files** | `layer_check.iter_source_files()` drops any path with a `tests` component, plus `conftest.py` and `test_*.py`. The one carve-out is `_CORE_TEST_FRAMEWORK_PACKAGE = ("odoo", "tests")`, the shipped test *framework*: inside it only its own `test_*.py` and `conftest.py` are dropped, and `case.py`, `common.py`, `http.py` and the rest **are** scanned |
| **`odoo.tests` is exempt from `core-does-not-depend-on-addons`** | `CORE_PACKAGES_EXEMPT_FROM_ADDON_CONTRACT`: the framework's job is to drive application code, and its one addon reach (`tests/http.py` → `odoo.addons.bus`) is deferred and guarded by `if "bus.bus" in self.env.registry:`. Every other core package is in scope (`test_core_source_covers_every_core_package`). Were `odoo/tests` skipped wholesale, this exemption would be dead code — which is the proof for the row above |

`core-does-not-depend-on-addons` is the mirror of `facade-boundary`: that one
stops addons reaching into ORM internals, this one stops the framework depending
on its own consumer. It ships **two pinned `KNOWN_VIOLATIONS` rules**
(`odoo.service` → `odoo.addons.base.models.ir_cron` / `…ir_job`), which the
report expands to **4 tolerated edges**, one per call site. Both intentional;
reasoning in **Known boundary exceptions** in [`gates.md`](gates.md).

## Coupling the import graph cannot see

`layer_check.py` reasons about **import** edges. Four coupling surfaces in this
tree produce none. Each has its own gate.

| Surface | Spelled as | Gate |
|---|---|---|
| mixin composition | `self.<sibling>` | `mixin_coupling_check.py` |
| Layer → runtime | `self.env.<m>`, `self.pool.<m>` | `env_surface_check.py`, `pool_surface_check.py` |
| framework → addon models | `env["res.users"]` — a string | `env_model_surface_check.py`, `model_member_surface_check.py` |
| cycles inside one layer | every edge stays in-layer, so no direction rule sees it | `py_cycle_check.py` |

### The five mixin compositions

A root class over `__slots__ = ()` mixins collaborating through `self`.
`BaseModel` is the largest, composed from 26
`__slots__ = ()` mixins by multiple inheritance — 18 public (`CreateMixin` …
`AccessMixin`) plus 8 private
(`_PropertiesMixin`, `_QueryMixin`, `_ConstraintsMixin`, `_DisplayNameMixin`,
`_FieldComputeMixin`, `_HooksMixin`, `_MagicFieldsMixin`, `_ModelMetadataMixin`).

`mixin_coupling_check.py` reconstructs the call graph and ratchets it exact-mode,
per composition. Measured by a live run of that gate:

| Composition | Units | Edges | `cyclic_edges` | `unowned_shared_state` | Root dominates its leaves? |
|---|---:|---:|---:|---:|---|
| `BaseModel` (`orm/models/`) | 31 | 105 | 0 | 4 | no |
| `Field` (`orm/fields/`) | 5 | 8 | 0 | 1 | **yes** |
| `Registry` (`orm/runtime/`) | 6 | 9 | 0 | 0 | **yes** |
| `Request` (`http/request_class.py`) | 4 | 1 | 0 | 8 | no |
| `Cursor` (`db/cursor.py`) | 3 | 3 | 0 | 5 | **yes** |

The last column is the shape claim, not a line count: a root larger than all its
leaves put together is a composition that has not actually been decomposed.
`BaseModel` is the target — its root is a fraction of its leaves — and three of
the other four still invert it. Line counts are deliberately not tabulated: they
move on every edit and carry no architectural signal the direction does not.

**Read `cyclic_edges` and `unowned_shared_state` as a pair, never `cyclic_edges`
alone.** An edge is recorded only where the reached member is bound in some
unit's **class body**. State assigned in a constructor and declared only in the
typing stub is read by everyone and owned by nobody, so it produces no edge —
and the stub is excluded from being a unit precisely so it cannot absorb them.
Deleting one line (`models: dict[str, type[BaseModel]]`) from `Registry`'s class
body, with no behaviour change, once took `cyclic_edges` from 4 to 2. The two
numbers move in opposite directions, so hiding an edge fails the ratchet twice.

`unowned_shared_state` is what each root holds without an owner:

| Root | n | Members |
|---|---:|---|
| `BaseModel` | 4 | `env`, `_ids`, `_prefetch_ids`, `_log_access` — the recordset's identity, assigned by `IterationMixin.__init__` |
| `Field` | 1 | `description_attrs` |
| `Request` | 8 | the request's identity, declared on `RequestState` |
| `Cursor` | 5 | `_cnx`, `_obj`, `_thread`, `_schema_cache`, `_before_statement` |

Under assignment-site ownership `BaseModel` still shows a 2-cycle,
`_metadata` ⇄ `iteration`; that one is open.

**`BaseModel` is measured on two graphs, not one.** A mixin is a fragment of
*one class*, so calling a sibling's method on another recordset of the same
model couples exactly as much as calling it on `self`. Following locals bound
from `self.browse(…)`, `self.filtered(…)`, `self.sudo()` and the rest
(`RECORDSET_PRODUCERS`) adds 8 edges — 105 → 113 — and is ratcheted separately
(`recordset_max_scc` 1, `recordset_cyclic_edges` 0,
`recordset_scc_without_base` 1). A cycle spelled through a recordset therefore
fails CI even where the `self`-only numbers stay clean. The other four are
`self`-only: a `Field` holds no recordset of itself.

Units are **file-level**, cross-checked against the runtime `BaseModel.__mro__`
rather than against themselves — and they are not the bases. It counts
*file-level* units — 31, since `read_group/` contributes five (`_empty`, `fill`,
`format`, `mixin`, `sql`) and `base.py` is itself a unit — not the 26 bases.

```bash
python tooling/architecture/mixin_coupling_check.py            # report
python tooling/architecture/mixin_coupling_check.py --check    # CI
python tooling/architecture/mixin_coupling_check.py --explain search read
python tooling/architecture/mixin_coupling_check.py --composition Field \
    --explain _field_convert _field_metadata
```

#### The design rule for a new mixin

**A leaf that nothing in the composition depends on cannot close a cycle.** Put
new behaviour on one.

| Rule | Evidence |
|---|---|
| Move the *declaration*, not just the methods — a unit owns what its class body binds | moving `Registry`'s methods without the container left `cyclic_edges` at 6, worse than the original 4, because the new leaf then reached the root for the state it was supposed to own |
| The obvious home is often the cycle | `_compute_field_value` belonged on `RecomputeMixin` by name; `traversal` already reaches `recompute` through `flush_model`, so its `self.filtered("id")` would have added `recompute → traversal` and closed a 2-cycle. On its own leaf (`_FieldComputeMixin`) the same three dependencies — `traversal`, `_constraints`, `_metadata` — close nothing. The gate reported it on the first run |

`base.py` is the target state that rule aims at: **in-degree 0, out-degree 0, in
both views.** It holds `__slots__`, `_register`, two setup hooks,
`get_base_url`, the deprecated `_cr`, and the three registration calls. Five
units depend on `_query` (`read`, `search`, `recompute`, `read_group/mixin`,
`read_group/sql`), which is where query construction went when it was taken off
the root.

#### Discovery is part of the gate

`test_mixin_coupling_check.py` **discovers composition roots from the tree** — a
class with two or more `*Mixin` bases whose own name does not end in `Mixin` —
and fails if one is absent from `COMPOSITIONS`. It finds exactly the five above.
`ReadGroupMixin` is three mixins wide but is a *unit* of `BaseModel`, which is
what the name test excludes.

Its scope was `odoo/orm` until `Cursor` showed that a coverage list narrower than
the thing it guards reproduces the bug it exists to catch. Two filter changes
were needed to see `db/`'s pair, both verified neutral for the other four:
`_is_composed_class` also matches a class by its **own** `*Mixin` name, because
`db/`'s mixins are bare classes with no stub to inherit; and `collect_units`
skips `tests` packages, because `db/` and `http/` carry test doubles that inherit
the real mixins (`_FakeRequest`, `_FractionOnly`, `_MetricsCursor`).

For `Field` the units are the mixin composition only. Concrete field types are
*subclasses* and override base methods freely — `BaseString` overrides 4 of
`Field`'s 10 cache methods — but that is the override surface, a different graph.

### The layering is true of imports and false of the runtime graph

Layers 1 and 2 reach the runtime through `self.env` and `self.pool`, not through
imports. `orm-layer1-below-models-and-runtime` and `orm-models-below-runtime`
are clean and always will be, because that reach produces no import edge.

**Layer 1 is the heavier consumer on both channels.** Measured:

| Channel | Layer 1 (`orm/fields`, `orm/domain`) | Layer 2 (`orm/models`, `orm/registration.py`) |
|---|---:|---:|
| `Registry` accesses | **30** | 28 |
| `pool[<model>]` subscripts | **5** | 3 |
| distinct `Registry` members | 9 | **15** |
| unsanctioned `Environment` privates | **4** | 2 |
| accesses to those privates | **10** | 3 |

The inversion is one of volume, not of kind: Layer 2 reaches more *distinct*
members, and has private reaches of its own (`_ensure_field_triggers`,
`_init_modules`, `_database_translated_fields`,
`_database_company_dependent_fields`).

**Consequence:** a reader who takes the contracts as the whole picture predicts
the wrong blast radius for a change to `Environment` or `Registry`. Recorded as
[`risks.md`](risks.md) R2. Both gates draw their layer scope from the shared
`tooling/architecture/_orm_layer_scope.py`, so the two cannot drift apart, and a
new ORM module must be given a layer there or an argued exemption.

Two counting traps in that table, both of which produced a wrong figure before
they were named:

- A run's own header prints the **raw** private width (6 and 4), which includes
  the members `SANCTIONED_PRIVATE` blesses. The table is the *unsanctioned*
  count the gate pins, so a run and this page will not show the same pair.
- **4 is Layer 1's share, not the union.** The distinct private set across the
  whole ORM is 5, because `_field_depends_context` is reached from both
  packages. Quoting the union as one layer's figure is the slip that had this
  page and `env_surface_check.py`'s own docstring agreeing with each other while
  neither agreed with the checker.

**The `init_models` window: closed, but the shape is not.**

| | |
|---|---|
| Was | `_post_init_queue`, `_foreign_keys`, `_relation_reflections`, `_is_install` created in `init_models`' `try:` and `del`-eted in its `finally:` — alive only for that call. Layer 1 (`fields/relational/many2many.py`) wrote to the third, which worked solely because `update_db` runs inside the window. |
| Caught by | nothing. No declaration of the ordering; an `AttributeError` at module-install time was the only signal. |
| Now | one `InitModelsPhase` (`orm/runtime/_init_phase.py`) behind `Registry.init_phase`, a property that raises a `RuntimeError` naming the window when closed. Layer 1 calls `pool.add_relation_reflection(...)`. |
| Still open | `registration.py` reads `Registry._init_modules` to ask whether an install is in flight — same shape, pinned in `pool_surface_check.py`, same remediation: a public predicate. |

[`risks.md`](risks.md) R1, the register's first closed entry.

### The set of addon-owned models the framework may name is closed

The framework's largest real coupling to its consumer is spelled as a string
(`env["res.users"]`) and produces no import edge. Two gates bound it:

| Gate | Bounds | Pinned as |
|---|---|---|
| `env_model_surface_check.py` | *which models* are reached | an exact set, plus **7 subtrees at zero reaches** |
| `model_member_surface_check.py` | *which members* of them are called | against the `Protocol`s in `orm/_protocols.py` |

The seven zero-reach subtrees — `orm/components`, `libs`, `db`, the
`api`/`fields`/`models` shims, `_monkeypatches` — each already claim that
property for an independent reason, so a first reach there is a contradiction
rather than a cost.

`orm/_protocols.py` is the third leg: it declares what the framework *requires*
of those models, narrowly. `ResUsersProtocol` names the members the core cannot
work without, not the hundreds `res.users` has —
`addons/base/tests/test_framework_contracts.py` checks each Protocol against the
live model, which is what catches `base` renaming a member under the framework.

### Direction rules are blind to cycles

Every edge of a cycle can sit inside one layer and cross no boundary. Python
hides this better than ESM does — a partially-initialised module is a live
object, so a cycle usually *works* until an entry point changes.
`py_cycle_check.py` reconstructs the import graph to find them. **The ORM has
none.** Four are pinned, all the benign package↔submodule shape:

```
odoo.modules <-> odoo.modules.db
odoo.cli     <-> odoo.cli.command
odoo.service <-> odoo.service._prefork <-> odoo.service._threaded <-> odoo.service.server
odoo.tests   <-> odoo.tests.common <-> odoo.tests.http
```

Function-local imports are deliberately not counted as edges: a deferred import
is the sanctioned way to break a cycle.

## Seams that keep the layers decoupled

Every downward-only rule has a counterpart seam that lets the lower layer still
be *driven* by the upper one. **Adding a cross-layer dependency means adding a
seam, not an import.**

| Seam | Mechanism | ADR |
|---|---|---|
| `db/` ↔ ORM | `orm/runtime/savepoint.py` assigns `_OrmFlushingSavepoint` to `BaseCursor._flushing_savepoint_cls` at import, so `db/` never imports the ORM | 0003 |
| `components/` ↔ runtime | `FieldCache`/`ComputeEngine` take callbacks for SQL and recompute, so the engine never imports `Environment` | 0002 |
| Layer 1 ↔ `BaseModel` | the model layer injects `BaseModel` into `orm/_recordset.py` via `set_base_model()`, so `fields/` and `domain/` recognise recordsets without importing Layer 2 | 0001 |
| CRUD ↔ persistence | the model mixins dispatch row I/O through `env.backend` | 0011 |
| framework ↔ addon models | string key (`env["res.users"]`), never an import | — |

**`env.backend` is non-optional and has two implementors**: `PostgresBackend`
adapts the port to the model's own `_*_sql` methods; `runtime/backend.py`'s
`InMemoryBackend` adapts it to `DictBackend` (ADR-0011 + its 2026-08-08
amendment). Production CRUD sniffs the test backend neither via
`transaction.storage` nor via a null check. Until 2026-08-08 a null
`env.backend` *was* the PostgreSQL implementation — an unnamed branch at fifteen
sites across nine files, which left the Protocol describing only the test double
and a differential suite with one object to compare against.

**Capabilities: 5 declared, 6 read sites, 3 of them instead of a port call.**
Two different measurements, both pinned by `test_backend_dispatch_surface.py`,
and a bare "three sites" states neither:

| Measure | Value | What it counts |
|---|---:|---|
| declared capabilities | 5 | `supports_parent_store`, `supports_record_rules`, `supports_joined_m2m_read`, `supports_column_scan`, `supports_translation_terms` (`runtime/backend.py`; both implementors set all five) |
| capability reads in the ORM | 6 | every `backend.supports_*` in non-test source |
| dispatch sites that **branch instead of calling the port** | 3 of 15 | `many2many.read`, `reference._reference_exists`, `textual._languages_in_sync_with` |

The other three reads guard a site that *does* dispatch: `create._parent_store_create`
and `write._parent_store_update_prepare` on `supports_parent_store`, and
`_query._search` on `supports_record_rules`.

The three that branch are where the two backends run genuinely different
*algorithms* rather than two implementations of one. The sharpest is
`Many2many.read`: the SQL path fuses a JOIN into the comodel's `Query`, and the
port's `read_m2m_pairs` signature has nowhere to put it.
