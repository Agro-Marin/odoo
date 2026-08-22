# ADR-0004: `libs/` (agnostic) vs `tools/` (Odoo-coupled) split

- **Status:** Accepted
- **Date:** 2026-06-23 (retroactive — records an existing decision)

## Context

`odoo/tools/` is a grab-bag. Some of it is framework-independent (date math,
number rounding, HTML sanitising, set expressions); some requires the ORM,
config or runtime (`safe_eval` of domains, `ormcache`, translation loading).
Both kinds sit in the same modules, so nothing in `tools/` can be imported
without risking the framework coming with it.

## Decision

`odoo/libs/` holds **dependency-free** utilities — no `odoo.*` import.
`odoo/tools/` holds **Odoo-coupled** utilities. Code moving to `libs/`
relocates its implementation and updates callers; where the historical
`tools.*` path must keep working, a plain re-export or wrapper is kept — not a
`DeprecationWarning` shim. `tools/__init__.py` re-exports `libs/numbers`'s
`float_compare`/`float_round`; `tools/template_inheritance.py` wraps
`libs/xml/template_inheritance.py` with Odoo error handling.

Membership test for new code — **import-clean AND general-purpose**:

- no `odoo` import needed *and* not framework-specific by purpose →
  `odoo/libs/<area>/`
- needs config / ORM / runtime, **or** is framework-specific even without an
  `odoo` import → `odoo/tools/`

Only the first half is gateable (the `libs-is-dependency-free` contract — read
it as *libs-is-odoo-free*; `libs/` freely uses lxml, PIL, babel and
`odoo_rust`). The second half is judgement, and it exists so `libs/` does not
become "everything that compiles without odoo": a module that is import-clean
but exists only to instrument the ORM stays in `tools/`. Generic profiling
infrastructure (frame/thread sampling, speedscope emission) is general-purpose
and lives in `libs/profiling/`; an ORM-shaped profiler on top of it is not.

**Worked example — splitting a mixed module by purpose.** The former
tools/sql.py (2026-08; unbackticked, the split removed the file — see
Amendments) was three things: the general-purpose `SQL` composition builder
with its string/trigram helpers, ~30 cursor-executing DDL helpers, and one
recordset operation. The mechanical import test would admit all of it to
`libs/`. The hybrid rule split it:

- `SQL` builder + string/trigram helpers → `libs/sql/`
- DDL helpers → `odoo/db/schema.py` (PostgreSQL-generic but cursor-coupled)
- `increment_fields_skiplock` → `BaseModel._increment_fields_skiplock`, an ORM
  concern the façade boundary keeps out of addons

The `odoo.tools` façade re-exports the builder and string helpers, so
`from odoo.tools import SQL` still resolves. DDL helpers come from
`odoo.db.schema` — `tools` cannot import `db`, because `db` imports `tools`.

## Consequences

- `libs/` is reusable and testable alone. The direction is one-way (`tools/`
  may use `libs/`, never the reverse), enforced by `layer_check.py`'s
  `libs-is-dependency-free` contract and `libs_facade_check.py`.
- Existing `tools.*` import paths keep working.
- Cost: an ongoing migration. Framework-free helpers remain under `tools/`
  (`query`), and could move by this record's own rule. The gates enforce "no
  `libs/` → `odoo.*` edge", not "every framework-free helper has moved".

### Asset pipeline relocation (resolved 2026-06)

The ESM/esbuild asset pipeline (`esbuild`, `esm_bridges`, `esm_graph`,
`esm_registry`) started in `libs/` but imports `odoo.api`, `odoo.tools`,
`odoo.modules` and `odoo.addons`. It failed the contract and moved to
`odoo/tools/assets/`. The dependency-free helper it builds on
(`libs/asset_log.py`) stays in `libs/`. All in-repo importers were updated —
`base/models/assetsbundle/`, `base/models/ir_qweb.py`,
`web/controllers/webclient.py`, the asset tests.

`libs/filesystem/osutil.py` imported `odoo.release` for a Windows service name;
it now takes the name as a parameter (`is_running_as_nt_service`) supplied by
`service/lifecycle.py`. With that, `libs/` has no remaining known exception.

## Enforcement

`tooling/architecture/layer_check.py`, contract `libs-is-dependency-free`,
drift-zero: no `odoo.*` import may be added under `libs/`. Run the checker for
the contract's live status.

## Amendments

A path named without backticks below no longer exists; backticking asserts it
does.

### 2026-08-07 — `assetsbundle.py` is a package; `hashing`/`nplusone` have moved

- **The assets bundle is a package**, `base/models/assetsbundle/`, not the
  single module cited. Corrected in place; this is what
  `test_adr_coherence.py`'s addon-relative path check found first.
- **`hashing` has left `tools/`** for `odoo/libs/hashing.py`. Of the three
  helpers the Consequences cited as awaiting migration, only `query`
  (`odoo/tools/query.py`) still illustrates the point — which survives, since
  the point was about the gate's scope, not about migration being complete.

Open question this record's rule raises and does not answer:
`odoo/libs/_field_access/` is import-clean and legal under the contract, but
its purpose is the ORM's field cache (`batch_cache_fill`, `to_prefetch_ids`,
`sort_ids_by_cache`) and its only production consumer is
`odoo/orm/models/mixins/traversal.py`. By the hybrid rule it is on the wrong
side, and its leading underscore says so. That is a decision, and wants its own
record.

### 2026-08-07 — the live contract status is no longer restated here

Enforcement said the contract was "currently **clean at zero**". That is a fact
about a moment in an immutable record, so it could only become false.

### 2026-08-09 — four more citations aged out, one wrong the day it was written

- **The 2026-08-07 claim that "`nplusone` no longer exists under either name"
  is false, and was false when written.** `025bfb53b19` renamed
  tools/nplusone.py to `odoo/libs/profiling/nplusone.py`; the file is live,
  gated by `ODOO_NPLUSONE=1`, activated in `681c5f4a342` (2026-07-08), an
  ancestor of the amendment commit. Kept rather than corrected: `nplusone` was
  never an open migration item — import-clean and framework-specific by
  purpose, it belongs in `libs/profiling/`, where it already was.
- **tools/float_utils.py no longer exists.** The re-export now happens inline
  in `tools/__init__.py`. Corrected in place; the point it illustrates holds.
- **libs/constants.py is deleted, not merely still in `libs/`.**
  `4803b9f765c` removed it — "whose every name was framework vocabulary the
  dependency-free layer had no business holding". `libs/asset_log.py`, named in
  the same sentence, is unaffected. Corrected in place.
- **tools/sql.py no longer exists at all**, not merely split. `086585a1731`
  carried out the split the worked example argues for, leaving no file to
  re-export from. Un-backticked above; the argument is unaffected.
