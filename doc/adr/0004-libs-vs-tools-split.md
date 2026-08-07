# ADR-0004: `libs/` (agnostic) vs `tools/` (Odoo-coupled) split

- **Status:** Accepted
- **Date:** 2026-06-23 (retroactive — records an existing decision)

## Context

`odoo/tools/` is a historical grab-bag: some of it is genuinely
framework-independent (date math, number rounding, HTML sanitising, set
expressions), while some of it requires the ORM, the config, or the runtime
(`safe_eval` of Odoo domains, the `ormcache` decorator, translation loading).
The two kinds are mixed in the same modules, so nothing in `tools/` can be
trusted to be importable without dragging in the framework.

## Decision

Introduce `odoo/libs/` as the home for **dependency-free** utilities — code that
does not import `odoo.*` — and keep `odoo/tools/` for **Odoo-coupled**
utilities. Code moved from `tools/` to `libs/` is migrated by relocating the
implementation and updating callers; where the historical `tools.*` import path
must keep working, a thin re-export or wrapper is left in `tools/` — e.g.
`tools/float_utils.py` re-exports `libs/numbers`, and
`tools/template_inheritance.py` is a thin Odoo-error-handling wrapper over
`libs/xml/template_inheritance.py`. These are plain re-exports/wrappers, not
`DeprecationWarning` shims.

Rule of thumb for new code — **import-clean AND general-purpose**:

- no `odoo` import needed *and* the helper is not framework-specific by purpose
  → `odoo/libs/<area>/`
- needs config / ORM / runtime, **or** is framework-specific even without an
  `odoo` import (e.g. an ORM-only profiler) → `odoo/tools/`

The membership test has two halves on purpose. The gate can only enforce the
first (the `libs-is-dependency-free` contract — read it as *libs-is-odoo-free*;
"dependency-free" is historical, `libs/` freely uses lxml/PIL/babel and
`odoo_rust`). The second half is a judgement call kept out of `libs/` so it does
not become "everything that compiles without odoo": a module that is import-clean
but exists *only* to instrument the ORM stays in `tools/`. Generic profiling
*infrastructure* (frame/thread sampling, speedscope emission) is general-purpose
and lives in `libs/profiling/`; an ORM-shaped profiler configured on top of it is
the framework-specific part.

A worked example of splitting a *mixed* module by this rule: `tools/sql.py`
(2026-08) was three things at once — the general-purpose `SQL` composition
builder with its string/trigram helpers, ~30 cursor-executing DDL helpers, and
one recordset operation. The mechanical import test would admit all of it to
`libs/` (none imports `odoo` at runtime), but the hybrid rule split it by
*purpose*: the `SQL` builder + string/trigram helpers → `libs/sql/`
(general-purpose); the DDL helpers → `odoo/db/schema.py` (PostgreSQL-generic but
cursor-coupled — `db/`, not the framework-free `libs/`); and
`increment_fields_skiplock` → a `BaseModel._increment_fields_skiplock` method (it
operates on records, an ORM concern, and the façade boundary keeps addons from
importing it out of `odoo.orm`). The `odoo.tools` façade re-exports the builder
and string helpers, so `from odoo.tools import SQL` still resolves; the DDL
helpers are imported from `odoo.db.schema` (tools cannot import `db` — `db`
imports tools).

## Consequences

- `libs/` is reusable and testable on its own; the dependency direction is
  one-way (`tools/` may use `libs/`, never the reverse) and is enforced by
  `layer_check.py`'s `libs-is-dependency-free` contract and `libs_facade_check.py`.
- The re-exports/wrappers keep existing `tools.*` import paths working.
- The cost: an ongoing migration. Some framework-free helpers still live under
  `tools/` (e.g. `hashing`, `query`, `nplusone`) and could move to `libs/` by
  this ADR's own rule; the boundary the gates enforce is "no `libs/` → `odoo.*`
  edge", not "every framework-free helper already lives in `libs/`".

### Asset pipeline relocation (resolved 2026-06)

The ESM/esbuild **asset pipeline** (`esbuild`, `esm_bridges`, `esm_graph`,
`esm_registry`) originally lived in `libs/` but is Odoo-framework-aware — it
imports `odoo.api`, `odoo.tools`, `odoo.modules`, and `odoo.addons`. It did
**not** satisfy the dependency-free contract and has been **relocated to
`odoo/tools/assets/`**. The dependency-free helpers it builds on
(`libs/asset_log.py`, `libs/constants.py`) remain in `libs/` (`tools/` may
import `libs/`, never the reverse). All in-repo importers
(`base/models/assetsbundle/`, `base/models/ir_qweb.py`,
`web/controllers/webclient.py`, and the asset tests) were updated.

`libs/filesystem/osutil.py` previously imported `odoo.release` for a Windows
service name; it now takes the name as a parameter (`is_running_as_nt_service`),
supplied by its caller in `service/lifecycle.py`. With that, **`libs/` is fully
dependency-free** — the contract has no remaining known exceptions.

## Enforcement

`tooling/architecture/layer_check.py`, contract `libs-is-dependency-free`
(currently **clean at zero**). The gate is **drift-zero** — no `odoo.*` import
may be added under `libs/`.

## Amendments

Append-only. An amendment corrects what this record says *about the repo*; it
never edits the decision above.

### 2026-08-07 — `assetsbundle.py` is a package; `hashing`/`nplusone` have moved

Three factual references had aged out of the tree. The first is corrected in
place because it is a citation, not a decision; the other two are recorded here
because correcting them would rewrite the Consequences' argument.

- **The assets bundle is a package now**, `base/models/assetsbundle/`, not the
  single module this ADR cited. It was itself decomposed after this ADR was
  written. Corrected in place above; this is what `test_adr_coherence.py`'s new
  addon-relative path check found first when it was added.
- **`hashing` is no longer under `tools/`.** The Consequences cite `hashing`,
  `query` and `nplusone` as framework-free helpers still awaiting migration.
  `hashing` completed that migration and now lives at `odoo/libs/hashing.py`;
  `nplusone` no longer exists under either name. Only `query` (`odoo/tools/query.py`)
  is still an example of the point being made — which the point survives, since
  it was about the gate enforcing "no `libs/` → `odoo.*` edge" rather than
  "every framework-free helper has already moved".

One open question this ADR's own rule raises and does not answer:
`odoo/libs/_field_access/` is import-clean and therefore legal under the
`libs-is-dependency-free` contract, but its purpose is the ORM's field cache
(`batch_cache_fill`, `to_prefetch_ids`, `sort_ids_by_cache`) and its only
production consumer is `odoo/orm/models/mixins/traversal.py`. By the hybrid rule
above — "framework-specific even without an `odoo` import → `odoo/tools/`" — it
is on the wrong side of the line, and its leading underscore says so. Resolving
that is a decision, not an amendment, and wants its own record.
