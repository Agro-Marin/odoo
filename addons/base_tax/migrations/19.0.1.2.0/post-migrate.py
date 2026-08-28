from odoo.db import schema

MOVES = (("account_tax", "account_tax_res_company_rel", "account_tax_id"),)


def migrate(cr, version):
    """Carry ``account.tax.company_id`` into the ``company_ids`` relation.

    Post, for the same reason as the tax group's own migration one version back:
    the many2many table is created by the registry update, so a pre-migrate has
    nothing to insert into, while the old column survives that update untouched.

    ``account.tax.repartition.line.company_id`` was a *stored related* of the
    tax's column. It carries no information the tax does not, so it is dropped
    rather than migrated -- ``company_ids`` there is an unstored related now.
    """
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
