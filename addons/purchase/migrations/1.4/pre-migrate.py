"""Pre-migration for Odoo 19 renamed purchase menu XML IDs.

Commit 6cd8a09a6464 added core/addons/purchase/views/purchase_menus.xml with
the new IDs but did not swap the manifest entry; commit 94ec6867 then updated
downstream references (marin, purchase_group_readonly) to the new IDs,
breaking any DB that still holds the pre-Odoo 19 names in ir_model_data.

This pre-migration renames the three affected rows in place, preserving
res_id mapping so existing ir.ui.menu records (1851, 1854, 1855 on marin190)
stay intact and the loader finds them when purchase_menus.xml is parsed
immediately afterwards.
"""

_RENAMES = (
    ("purchase_report_main", "menu_purchase_reporting"),
    ("purchase_report", "menu_purchase_report"),
    ("product_product_menu", "menu_purchase_product_variant"),
)


def migrate(cr, version):
    if not version:
        return
    for old, new in _RENAMES:
        # Drop any stray row at the new name that does NOT match the old-name
        # row (left over from a previous partial upgrade that loaded
        # purchase_menus.xml without running this script). Safe no-op when
        # the DB is in its normal state.
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
