from odoo.tools.module_data import adopt_xmlids, retire_empty_module

MODULE = "account_coa"

# account extended these three views of account_coa under the same names; the
# fold makes each one view, so the extension's children follow the base view
# and the extension goes before its xml id can clash with the adopted one
MERGED_VIEWS = ("view_account_form", "view_account_list", "view_account_search")


def migrate(cr, version):
    if not version:
        return
    cr.execute("SELECT id FROM ir_module_module WHERE name = %s", [MODULE])
    row = cr.fetchone()
    if not row:
        return
    coa_id = row[0]
    cr.execute(
        """
        SELECT base.res_id, ext.res_id, ext.id
          FROM ir_model_data base
          JOIN ir_model_data ext
            ON ext.module = 'account' AND ext.name = base.name
               AND ext.model = 'ir.ui.view'
         WHERE base.module = %s AND base.model = 'ir.ui.view'
           AND base.name = ANY(%s)
        """,
        [MODULE, list(MERGED_VIEWS)],
    )
    for base_view, extension_view, extension_xmlid in cr.fetchall():
        cr.execute(
            "UPDATE ir_ui_view SET inherit_id = %s WHERE inherit_id = %s",
            [base_view, extension_view],
        )
        cr.execute("DELETE FROM ir_ui_view WHERE id = %s", [extension_view])
        cr.execute("DELETE FROM ir_model_data WHERE id = %s", [extension_xmlid])

    cr.execute(
        "SELECT name FROM ir_model_data WHERE module = %s AND model <> 'ir.module.module'",
        [MODULE],
    )
    adopt_xmlids(cr, MODULE, "account", [name for (name,) in cr.fetchall()])
    cr.execute("SELECT id FROM ir_module_module WHERE name = 'account'")
    account_id = cr.fetchone()[0]
    for table in ("ir_model_constraint", "ir_model_relation"):
        cr.execute(
            f"""
            DELETE FROM {table} coa
             WHERE coa.module = %s
               AND EXISTS (SELECT 1 FROM {table} kept
                            WHERE kept.module = %s AND kept.name = coa.name)
            """,
            [coa_id, account_id],
        )
        cr.execute(
            f"UPDATE {table} SET module = %s WHERE module = %s",
            [account_id, coa_id],
        )
    retire_empty_module(cr, MODULE)
