from odoo.db import schema

FIELDS = (
    "account_fiscal_country_id",
    "account_price_include",
    "tax_calculation_rounding_method",
)


def migrate(cr, version):
    if not version:
        return
    # the settings move here from account.config, whose columns account's own
    # upgrade drops after this module has loaded
    if not all(schema.column_exists(cr, "account_config", f) for f in FIELDS):
        return
    columns = ", ".join(FIELDS)
    updates = ", ".join(f"{f} = EXCLUDED.{f}" for f in FIELDS)
    cr.execute(
        f"""
        INSERT INTO tax_config (company_id, {columns},
                                create_uid, create_date, write_uid, write_date)
             SELECT company_id, {columns},
                    create_uid, create_date, write_uid, write_date
               FROM account_config
        ON CONFLICT (company_id) DO UPDATE SET {updates}
        """
    )
