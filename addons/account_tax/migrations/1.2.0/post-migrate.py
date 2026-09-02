from odoo.db import schema

MOVES = (("account_tax", "account_tax_res_company_rel", "account_tax_id"),)


def migrate(cr, version):
    if not version:
        return

    for table, rel, column in MOVES:
        if not schema.column_exists(cr, table, "company_id"):
            continue
        if not schema.table_exists(cr, rel):
            raise RuntimeError(
                f"{rel} is absent: {table}.company_ids did not reach the schema, "
                f"so migrating company_id into it would lose every row."
            )
        cr.execute(
            f"""
            INSERT INTO {rel} ({column}, res_company_id)
                 SELECT id, company_id
                   FROM {table}
                  WHERE company_id IS NOT NULL
            ON CONFLICT DO NOTHING
            """
        )
        cr.execute(f"ALTER TABLE {table} DROP COLUMN company_id")

    if schema.column_exists(cr, "account_tax_repartition_line", "company_id"):
        cr.execute("ALTER TABLE account_tax_repartition_line DROP COLUMN company_id")
