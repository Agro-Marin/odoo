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
utilities. Code moved from `tools/` to `libs/` leaves behind a thin
re-export/deprecation shim in `tools/` (e.g. `tools/intervals.py` is a
`DeprecationWarning` shim over `libs/intervals.py`; `tools/template_inheritance.py`
is a thin Odoo-error-handling wrapper over `libs/xml/template_inheritance.py`).

Rule of thumb for new code:

- no `odoo` import needed → `odoo/libs/<area>/`
- needs config / ORM / runtime → `odoo/tools/`

## Consequences

- `libs/` is reusable and testable on its own; the dependency direction is
  one-way (`tools/` may use `libs/`, never the reverse).
- The shims keep existing import paths working while callers migrate.
- The cost: an ongoing migration. Several modules still need to move (see the
  known exception), and callers should be moved off the deprecated `tools.*`
  re-exports over time.

### Asset pipeline relocation (resolved 2026-06)

The ESM/esbuild **asset pipeline** (`esbuild`, `esm_bridges`, `esm_graph`,
`esm_registry`) originally lived in `libs/` but is Odoo-framework-aware — it
imports `odoo.api`, `odoo.tools`, `odoo.modules`, and `odoo.addons`. It did
**not** satisfy the dependency-free contract and has been **relocated to
`odoo/tools/assets/`**. The dependency-free helpers it builds on
(`libs/asset_log.py`, `libs/constants.py`) remain in `libs/` (`tools/` may
import `libs/`, never the reverse). All in-repo importers
(`base/models/assetsbundle.py`, `base/models/ir_qweb.py`,
`web/controllers/webclient.py`, and the asset tests) were updated.

`libs/filesystem/osutil.py` previously imported `odoo.release` for a Windows
service name; it now takes the name as a parameter (`is_running_as_nt_service`),
supplied by its caller in `service/lifecycle.py`. With that, **`libs/` is fully
dependency-free** — the contract has no remaining known exceptions.

## Enforcement

`tooling/architecture/layer_check.py`, contract `libs-is-dependency-free`
(currently **clean at zero**). The gate is **drift-zero** — no `odoo.*` import
may be added under `libs/`.
