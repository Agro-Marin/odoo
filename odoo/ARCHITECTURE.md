# Odoo Framework Core — Architecture

High-level structure, layering, and dependency rules for the framework core in
`odoo/` (the ORM, persistence, HTTP, server, module system, and utilities).
This is the framework-level counterpart to the per-addon
`machine_doc_v1/ARCHITECTURE.md` maps.

> **This document is enforced.** The dependency rules below are checked
> mechanically by `tooling/architecture/layer_check.py` and gated in CI
> (`.github/workflows/architecture.yml`). The rationale for each rule lives in
> the ADRs under `doc/adr/`. Docs explain *why*; the checker guarantees *that*.

## Identity

- **What:** A fork of Odoo Community 19.0 (`19.0-marin`), framework + base addons.
- **Runtime floor:** Python 3.14 (pinned: MIN = MAX = 3.14), PostgreSQL ≥ 18
  (`odoo/release.py`).
- **Posture:** No upstream backward-compatibility constraint on `19.0-marin` —
  the monoliths (`models.py`, `fields.py`, `api.py`, `http.py`, `sql_db.py`,
  `service/server.py`) have been decomposed into layered packages.

## Subsystem map

```
odoo/
├── orm/            The ORM, as an explicit 4-layer architecture (see below)
│   ├── primitives, parsing, validation, constants, _typing   (Layer 0)
│   ├── fields/, domain/                                       (Layer 1)
│   ├── models/  (BaseModel + 18 mixins, metaclass)            (Layer 2)
│   ├── runtime/ (Environment, Registry, Transaction, backend) (Layer 3)
│   └── components/  pure-Python cache / compute / unit-of-work (cross-cutting)
├── api/ · fields/ · models/   Thin public re-export shims over orm/ (stable imports)
├── db/             Decomposed sql_db.py: pool, cursor, ddl, savepoint,
│                   schema_cache, bulk, metrics, lifecycle, dsn, errors
├── http/           Decomposed http.py: application, dispatcher, routing,
│                   session, request, response, stream, csrf
├── service/        Process lifecycle + servers: threaded / prefork / event,
│                   workers, wsgi, cron, retrying
├── modules/        Module graph (topological), loading, migration, registry/
├── tools/          Odoo-COUPLED utilities (need ORM / config / runtime)
│   └── assets/     Server-side asset pipeline (esbuild + ESM graph/bridges/registry)
├── libs/           Odoo-AGNOSTIC utilities (no framework dependency)
├── _monkeypatches/ Explicit, import-hook-driven third-party patches
└── cli/            Command-line entry points
```

### Public import surface

Application and addon code imports from the stable façades — **`odoo.api`,
`odoo.fields`, `odoo.models`** — not from `odoo.orm.*` submodules directly.
The façades exist as `__init__.py` re-export files specifically to keep the
ORM's internal layout free to evolve without breaking imports across hundreds
of addons. Each façade declares an explicit `__all__` (its curated public
surface), and the boundary is **enforced**: the `facade-boundary` contract
fails CI if any file under **either** addon tree — `odoo/addons/**` or the
sibling `addons/**` — imports `odoo.orm.*` at runtime (`if TYPE_CHECKING:`
imports are exempt). See ADR-0008.

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
            ▲
            └─ components/   FieldCache · ComputeEngine · UnitOfWork · ModelGraph
               Pure Python. No odoo imports at runtime. Collaborators injected.
```

- **Layer 0** imports no higher *ORM* layer — that is the enforced
  `orm-layer0-is-foundational` rule. It may still use dependency-free helpers
  from `odoo.tools`/`odoo_rust` (e.g. the `SQL` builder in `primitives.py`); the
  invariant is "nothing from `fields`/`models`/`runtime`", not "nothing from
  `odoo`".
- **Layer 1** (`fields`, `domain`) depends only on Layer 0.
- **Layer 2** (`models`) builds on Layers 0–1.
- **Layer 3** (`runtime`) builds on Layers 0–2.
- **`components/`** is the cache/compute/unit-of-work engine, written as pure
  Python with zero framework imports so it is unit-testable without an
  `Environment`, `Registry`, or database. It receives its collaborators by
  injection. See ADR-0002. Framework code reaches the per-transaction
  `FieldCache`/`ComputeEngine` through the curated id-level facade
  **`env._core`** (`OrmCore`); the raw objects are private to `Transaction`
  (`_cache_store`/`_compute_engine`), and the legacy recordset-level wrapper is
  `env.cache`. See ADR-0010.

## Enforced dependency rules

| Contract | Rule | Status |
|----------|------|--------|
| `libs-is-dependency-free` | `odoo/libs/**` must not import `odoo.*` (except `odoo.libs`) | ✅ clean |
| `db-is-orm-agnostic` | `odoo/db/**` must not import `odoo.orm/models/fields/api` | ✅ clean |
| `orm-components-are-pure-python` | `odoo/orm/components/**` must not import `odoo.*` | ✅ clean |
| `orm-layer0-is-foundational` | Layer-0 (`primitives`, `parsing`, `validation`, `constants`, `_typing`) imports no higher ORM layer | ✅ clean |
| `orm-layer1-below-models-and-runtime` | `orm/fields` & `orm/domain` must not import `orm/models` or `orm/runtime` | ✅ clean |
| `orm-models-below-runtime` | `orm/models` (Layer 2) must not import `orm/runtime` (Layer 3) | ✅ clean |
| `orm-seams-stay-below-models-and-runtime` | `orm/_recordset` & `orm/decorators` must not import `orm/models` or `orm/runtime` | ✅ clean |
| `facade-boundary` | addon code (`odoo/addons/**` **and** the sibling `addons/**`) must not import `odoo.orm.*` (use `odoo.api`/`odoo.fields`/`odoo.models`) | ✅ clean |

**All eight boundaries are clean at zero** — the framework core has no tolerated
exceptions. The gate is **drift-zero**: any *new* crossing fails CI. Should a
genuinely unavoidable exception arise, pin it (annotated) in `layer_check.py`'s
`KNOWN_VIOLATIONS` so it is visible and cannot multiply.

### Seams that keep the layers decoupled

- **`db/` ↔ ORM:** the cursor's flushing savepoint is injected via
  `BaseCursor._flushing_savepoint_cls`, so `db/` never imports the ORM (ADR-0003).
- **`components/` ↔ runtime:** `FieldCache`/`ComputeEngine` take callbacks for
  SQL and recompute, so the engine never imports `Environment` (ADR-0002).
- **Layer 1 ↔ `BaseModel`:** `fields/` and `domain/` recognise recordsets and
  `_search` overrides through `orm/_recordset.py`, into which the model layer
  injects `BaseModel` at import time — so Layer 1 never imports Layer 2 (ADR-0001).
- **CRUD ↔ persistence backend:** the model mixins (`create`/`write`/`read`/
  `search`/`unlink`) dispatch row I/O through `env.backend`. `None` is the
  PostgreSQL fast path (SQL emitted inline); a non-`None`
  `runtime/backend.py::InMemoryBackend` owns the DB-free in-memory variant of
  each operation — so the test backend is no longer sniffed (`transaction.storage`)
  inside production CRUD code (ADR-0011).

## Request lifecycle (HTTP)

```
WSGI  →  Application.__call__  →  Request (_post_init: session + db)
      →  _serve_static | _serve_nodb | _serve_db
            _serve_db: Registry → ir.http._match → Model.retrying(
                _authenticate → pre_dispatch → Dispatcher.dispatch(endpoint)
                → post_dispatch ) → commit/rollback → response + session save
```

`Dispatcher` has three subclasses (`HttpDispatcher`, `JsonRPCDispatcher`,
`Json2Dispatcher`) selected by `routing["type"]`.

## Known boundary exceptions (tracked debt)

**None.** All eight boundary contracts are clean at zero. The exceptions surfaced
by the checker's first run (2026-06) have all been paid down:

- **Asset pipeline** (`esbuild`, `esm_bridges`, `esm_graph`, `esm_registry`)
  relocated from `libs/` to `odoo/tools/assets/` (ADR-0004). The dependency-free
  helpers it builds on (`asset_log`, `constants`) remain in `libs/`.
- **`libs/filesystem/osutil.py`** no longer imports `odoo.release`; the Windows
  service name is passed in by the caller (ADR-0004).
- **Layer-1 → Layer-2 deferred `BaseModel` imports** in `orm/domain/ast.py` and
  `orm/fields/relational.py` replaced by the `orm/_recordset.py` injection seam
  (ADR-0001).

## Where to add code

- **A dependency-free helper** (no `odoo` imports) → `odoo/libs/<area>/`.
- **An Odoo-coupled helper** (needs config/ORM/runtime) → `odoo/tools/`.
- **A new field type** → `odoo/orm/fields/` (Layer 1; do not import models/runtime).
- **Model behaviour** → an existing or new mixin under `odoo/orm/models/mixins/`.
- **Cache/compute logic** → `odoo/orm/components/` (keep it pure Python).
- **A third-party patch** → `odoo/_monkeypatches/<module>.py` (see its README).

## Running the checks

```bash
python tooling/architecture/layer_check.py          # human-readable report
python tooling/architecture/layer_check.py --check   # CI mode: exit 1 on new violations
python tooling/architecture/layer_check.py --json     # machine-readable
```

## Quality gates beyond the boundaries

The boundary checker (ADR-0005) is one of three enforcement mechanisms. The
others keep the *non-structural* quality signals from regressing:

- **Drift-zero count ratchet** (`tooling/ratchet/`, ADR-0006) — turns mypy and
  ruff counts into one-way contracts. The committed floors live in
  `tooling/ratchet/baselines/`; CI fails on any increase, and (in `exact` mode)
  on an *un-committed* decrease, so every cleanup is locked in.

  ```bash
  python tooling/ratchet/test_ratchet.py     # self-test the tool
  python tooling/ratchet/ratchet.py --list    # current floors
  ```

- **DB-backed integration gate** (`.github/workflows/integration_tests.yml`,
  ADR-0007) — boots PostgreSQL 18 and runs the `base` suite, so the decomposed
  pieces are verified to *behave*, not just to import cleanly. This is the
  behavioural safety net under which the deeper in-layer refactors should land.

See also: `doc/adr/` (architecture decisions) and the `orm/__init__.py`
module docstring (the canonical statement of the layer model in code).
