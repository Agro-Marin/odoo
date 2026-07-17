"""Pre-migration for stock view/method/field renames (commit 158d4c68).

Commit 158d4c68 ("[FIX] stock: harden stock.move / ...") renamed several button
methods and product fields but shipped no migration script. Existing databases
still hold the OLD names inside stored ``ir_ui_view.arch_db`` (and one
``ir.actions.server`` code body). Odoo validates stored view arch against the
NEW Python model *before* reloading the module's XML, so ``-u`` crashes at
registry load with e.g. "Element '<xpath ...action_open_product_lot...>' cannot
be located in parent view" or an "Invalid field 'nbr_moves_in'" view error
(confirmed on marin190 while loading mrp, which inherits the stock product views).

This pre-migration rewrites the old identifiers to the new ones in stored view
arch and server-action code so revalidation passes; the module's XML reload
afterwards restores the canonical arch anyway. It also converts
``res.company.horizon_days`` from float to integer explicitly (the field became
``fields.Integer``) so the type change does not rely on implicit ORM coercion.

``arch_db`` is jsonb (a per-language dict); the technical identifiers below are
never translated and never appear as JSON keys, so a whole-value text replace is
safe and preserves the translation structure.
"""

from odoo.tools.sql import table_columns

# (old, new) — button/compute method names referenced by stored view buttons
# (type="object") and by ir.actions.server code.
_METHOD_RENAMES = (
    ("action_open_product_lot", "action_view_product_lot"),
    ("action_open_quants", "action_view_quants"),
    ("action_show_package", "action_view_package"),
    ("action_open_routes_diagram", "action_view_routes_diagram"),
)

# (old, new) — product.(product|template) field names referenced by stored views.
_FIELD_RENAMES = (
    ("nbr_moves_in", "count_moves_in"),
    ("nbr_moves_out", "count_moves_out"),
    ("nbr_reordering_rules", "count_reordering_rules"),
    ("reordering_min_qty", "reordering_qty_min"),
    ("reordering_max_qty", "reordering_qty_max"),
)


def migrate(cr, version):
    """Rewrite stale identifiers in stored view arch and server-action code.

    :param cr: database cursor
    :param version: installed module version; falsy on a fresh install
    """
    if not version:
        return  # fresh install: on-disk arch is already correct

    for old, new in _METHOD_RENAMES + _FIELD_RENAMES:
        cr.execute(
            """
            UPDATE ir_ui_view
               SET arch_db = replace(arch_db::text, %s, %s)::jsonb
             WHERE arch_db::text LIKE %s
            """,
            (old, new, f"%{old}%"),
        )

    for old, new in _METHOD_RENAMES:
        cr.execute(
            "UPDATE ir_act_server SET code = replace(code, %s, %s) WHERE code LIKE %s",
            (old, new, f"%{old}%"),
        )

    # res.company.horizon_days became fields.Integer; convert the column
    # explicitly (no fractional values exist in practice, round() is exact).
    # Guarded on the current type so a re-run (or a DB already converted by a
    # partial upgrade) skips the table rewrite instead of re-executing it.
    horizon_days = table_columns(cr, "res_company").get("horizon_days")
    if horizon_days is not None and horizon_days["udt_name"] != "int4":
        cr.execute(
            """
            ALTER TABLE res_company
            ALTER COLUMN horizon_days TYPE integer USING round(horizon_days)::integer
            """
        )
