# ADR-0008: Enforce the public façade boundary (`odoo.addons` → `odoo.orm`)

- **Status:** Accepted
- **Date:** 2026-06-25

## Context

The layered-ORM strategy (ADR-0001) rests on one promise in
`doc/architecture/ARCHITECTURE.md`: addon and application code imports from the
stable façades — `odoo.api`, `odoo.fields`, `odoo.models` — not from
`odoo.orm.*`. That promise is what lets Layers 0–3, the mixin decomposition and
the `components/` engine move without breaking imports across hundreds of
addons.

It was a convention, not a guarantee:

- `layer_check.py` (ADR-0005) derived its scanned files from contract `source`
  prefixes, all under `odoo.libs` / `odoo.db` / `odoo.orm`. It never scanned
  `odoo/addons/`, so no contract said addon code must use the façade.
- The boundary was breached 35 times in `odoo/addons/base` — mostly gratuitous
  `from odoo.orm._typing import ValuesType`, a name the façades already
  re-export, plus forced bypasses (`add_field`, `pop_field`) with no façade
  alternative.
- The façades carried no `__all__`, so the public surface was whatever happened
  to be imported, and `import *` leaked ORM internals.

Documenting a guarantee the tooling does not enforce invites the drift it warns
against.

## Decision

1. **Complete the façades.** Surface `add_field` / `pop_field` on
   `odoo.models` and `COLLECTION_TYPES` on `odoo.fields`, so every symbol an
   addon needs has a façade home.
2. **Curate the surface.** Give `odoo/api`, `odoo/fields`, `odoo/models` an
   explicit `__all__`.
3. **Pay down the bypasses.** Rewrite all 35 `odoo.orm.*` imports under
   `odoo/addons/**` to use the façades.
4. **Enforce it.** Add the `facade-boundary` contract to `layer_check.py`:
   files under `odoo.addons` may not import `odoo.orm.*` at runtime.
   `if TYPE_CHECKING:` imports are exempt, as in every other contract. The
   façades are not under `odoo.orm`, so importing them is legal by
   construction.

That brought the core to **eight** drift-zero contracts as of 2026-06-25, all
clean at zero on that date. The live set is `layer_check.py`'s `CONTRACTS`.

## Consequences

- A new `odoo.orm.*` import in any addon fails CI, with a pointer to the façade
  to use instead.
- The ORM's internal layout can be refactored freely: the blast radius of an
  internal move is the façade re-export line, not hundreds of addon files.
- `__all__` makes the public surface reviewable and diffable, and stops
  `import *` leaking internals.
- A genuinely public new ORM symbol must be added to a façade and its `__all__`
  to be usable from addons — deliberate friction that keeps the surface curated.
- The checker now also walks `odoo/addons/**`, which at this decision took it
  from ~150 files to 314; still sub-second. ADR-0009 widened it again.

## Enforcement

`tooling/architecture/layer_check.py`, `facade-boundary` contract, gated via
`--check` (ADR-0005), drift-zero. Covered by
`tooling/architecture/test_layer_check.py`
(`test_addon_importing_orm_internal_is_a_violation`,
`test_addon_importing_facades_is_clean`,
`test_addon_type_checking_import_of_orm_is_exempt`,
`test_facade_boundary_scans_the_addon_tree`) and the standing
`test_framework_core_has_no_new_violations` guard.

## Amendments

### 2026-08-07 — the contract count and scanned-file count are now dated

"Eight drift-zero boundary contracts, all clean at zero" and "the checker now
walks 314 files" both read as claims about today. The contract set has grown
past eight, and ADR-0009 widened the façade scope to both addon trees a
fortnight later. Both now name the moment they describe.

### 2026-08-07 — the architecture front door moved to `doc/architecture/`

This record cited the front door at the path it held inside the core package
until 2026-08-07. That page described the whole repository — its gate catalog
covers `addons/**` JS and the repo-wide `eslint`/`tsc` ratchets — while filed
one level below its own scope. Widening `doc_link_gate.py` to the set found 15
broken references. Corrected in place: the Context citation of the promise this
decision rests on.
