# ADR-0008: Enforce the public façade boundary (`odoo.addons` → `odoo.orm`)

- **Status:** Accepted
- **Date:** 2026-06-25

## Context

The whole layered-ORM strategy (ADR-0001) rests on one promise stated in
`odoo/ARCHITECTURE.md`: *addon and application code imports from the stable
façades — `odoo.api`, `odoo.fields`, `odoo.models` — not from `odoo.orm.*`
submodules directly.* Keeping that promise is what lets the ORM's internal
layout (Layers 0–3, the mixin decomposition, the `components/` engine) evolve
without breaking imports across hundreds of addons.

Until now that promise was a **convention, not a guarantee**:

- The architecture checker (`tooling/architecture/layer_check.py`, ADR-0005)
  derived its scanned files from the contract `source` prefixes, all of which
  lived under `odoo.libs` / `odoo.db` / `odoo.orm`. It **never scanned
  `odoo/addons/`**, so no contract said "addon code must use the façade."
- As a result the boundary was already breached 35 times in `odoo/addons/base`
  — mostly gratuitous `from odoo.orm._typing import ValuesType` (a name the
  façades already re-export), plus genuinely *forced* bypasses (`add_field`,
  `pop_field`) for which **no façade alternative existed**.
- The façades carried **no `__all__`**, so the "curated public surface" was
  implicit — whatever happened to be imported — and `import *` would leak ORM
  internals.

Documenting a guarantee the tooling did not enforce is worse than not claiming
it: it invites exactly the drift it warns against.

## Decision

Make the façade boundary a real, mechanically-enforced contract.

1. **Complete the façades.** Surface the previously-internal-only
   `add_field` / `pop_field` on `odoo.models`, and `COLLECTION_TYPES` on
   `odoo.fields`, so every symbol an addon needs has a façade home.
2. **Curate the surface.** Give `odoo/api`, `odoo/fields`, `odoo/models` each an
   explicit `__all__` listing exactly their public exports.
3. **Pay down the bypasses.** Rewrite all 35 `odoo.orm.*` imports in
   `odoo/addons/**` to import from the façades instead.
4. **Enforce it.** Add the `facade-boundary` contract to `layer_check.py`:
   files under `odoo.addons` may not import `odoo.orm.*` at runtime. Imports
   guarded by `if TYPE_CHECKING:` are exempt (they never execute and create no
   runtime coupling), consistent with every other contract. The façades
   themselves (`odoo.api` / `odoo.fields` / `odoo.models`) are not under
   `odoo.orm`, so importing them is allowed by construction.

This brings the framework core to **eight** drift-zero boundary contracts, all
clean at zero.

## Consequences

- The façade promise is now true and stays true: a new `odoo.orm.*` import in
  any addon fails CI, with a pointer to the façade to use instead.
- The ORM's internal layout can be refactored freely; the blast radius of an
  internal move is the façade re-export line, not hundreds of addon files.
- `__all__` makes the public surface reviewable and diffable, and stops
  `import *` from leaking internals.
- New genuinely-public ORM symbols must be added to a façade (and its `__all__`)
  to be usable from addons — a small, deliberate step that keeps the surface
  curated rather than accidental.
- The checker now walks `odoo/addons/**` (314 files vs. ~150 before); still
  sub-second.

## Enforcement

`tooling/architecture/layer_check.py` — the `facade-boundary` contract, gated in
CI via `--check` (ADR-0005), drift-zero. Covered by
`tooling/architecture/test_layer_check.py`
(`test_addon_importing_orm_internal_is_a_violation`,
`test_addon_importing_facades_is_clean`,
`test_addon_type_checking_import_of_orm_is_exempt`,
`test_facade_boundary_scans_the_addon_tree`) and by the standing
`test_framework_core_has_no_new_violations` regression guard.
