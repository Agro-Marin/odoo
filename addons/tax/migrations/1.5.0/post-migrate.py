from odoo.db import schema

FIELDS = ("account_sale_tax_id", "account_purchase_tax_id")


def migrate(cr, version):
    if not version:
        return
    # the default taxes move here from account.config, whose columns account's
    # own upgrade drops after this module has loaded
    if not all(schema.column_exists(cr, "account_config", f) for f in FIELDS):
        return
    updates = ", ".join(f"{f} = account.{f}" for f in FIELDS)
    cr.execute(
        f"""
        UPDATE tax_config tax
           SET {updates}
          FROM account_config account
         WHERE account.company_id = tax.company_id
        """
    )
