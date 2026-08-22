_RENAMES = (
    ("purchase_report_main", "menu_purchase_reporting"),
    ("purchase_report", "menu_purchase_report"),
    ("product_product_menu", "menu_purchase_product_variant"),
)


def migrate(cr, version):
    if not version:
        return
    for old, new in _RENAMES:
        cr.execute(
            """
            DELETE FROM ir_model_data
             WHERE module = 'purchase'
               AND name = %s
               AND res_id NOT IN (
                   SELECT res_id FROM ir_model_data
                    WHERE module = 'purchase' AND name = %s
               )
            """,
            (new, old),
        )
        cr.execute(
            """
            UPDATE ir_model_data
               SET name = %s
             WHERE module = 'purchase'
               AND name = %s
            """,
            (new, old),
        )
