from odoo.db import schema

TABLE = "account_tax_group"
REL = "account_tax_group_res_company_rel"


def migrate(cr, version):
    if not version:
        return
    if not schema.column_exists(cr, TABLE, "company_id"):
        return
    if not schema.table_exists(cr, REL):
        raise RuntimeError(
            f"{REL} is absent: account.tax.group.company_ids did not reach the "
            f"schema, so migrating company_id into it would lose every row."
        )

    cr.execute(
        f"""
        INSERT INTO {REL} (account_tax_group_id, res_company_id)
             SELECT id, company_id
               FROM {TABLE}
              WHERE company_id IS NOT NULL
        ON CONFLICT DO NOTHING
        """
    )
    cr.execute(f"ALTER TABLE {TABLE} DROP COLUMN company_id")
