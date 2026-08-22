from odoo.db.schema import table_columns

_METHOD_RENAMES = (
    ("action_open_product_lot", "action_view_product_lot"),
    ("action_open_quants", "action_view_quants"),
    ("action_show_package", "action_view_package"),
    ("action_open_routes_diagram", "action_view_routes_diagram"),
)

_FIELD_RENAMES = (
    ("nbr_moves_in", "count_moves_in"),
    ("nbr_moves_out", "count_moves_out"),
    ("nbr_reordering_rules", "count_reordering_rules"),
    ("reordering_min_qty", "reordering_qty_min"),
    ("reordering_max_qty", "reordering_qty_max"),
)


def migrate(cr, version):
    if not version:
        return

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

    horizon_days = table_columns(cr, "res_company").get("horizon_days")
    if horizon_days is not None and horizon_days["udt_name"] != "int4":
        cr.execute(
            """
            ALTER TABLE res_company
            ALTER COLUMN horizon_days TYPE integer USING round(horizon_days)::integer
            """
        )
