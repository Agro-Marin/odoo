from odoo.tools.module_data import adopt_xmlids

RECORDS = (
    "model_account_fiscal_position",
    "field_account_tax__fiscal_position_ids",
    "field_account_tax__original_tax_ids",
    "field_account_tax__replacing_tax_ids",
    "field_account_tax__display_alternative_taxes_field",
    "field_account_tax__is_domestic",
    "field_res_partner__property_account_position_id",
    "field_res_users__property_account_position_id",
    "access_account_fiscal_position",
    "account_fiscal_position_comp_rule",
)

# the account mapping and the chart-template header stay account's
ACCOUNT_FIELDS = ("account_ids", "account_map", "foreign_vat_header_mode")

RELATIONS = (
    "account_fiscal_position_account_tax_rel",
    "account_tax_alternatives",
    "account_fiscal_position_res_country_state_rel",
)


def migrate(cr, version):
    if not version:
        return
    # every row changes hands before account loads: an xml id left under
    # account would be orphaned when account stops declaring it, and
    # _process_end would delete the record behind it, and for a field its column
    cr.execute(
        "SELECT name FROM ir_model_data"
        " WHERE module = 'account' AND name ~ '^field_account_fiscal_position__'"
        " AND NOT (substring(name from 32) = ANY(%s))",
        [list(ACCOUNT_FIELDS)],
    )
    fields = [name for (name,) in cr.fetchall()]
    adopt_xmlids(cr, "account", "tax", (*RECORDS, *fields))
    # a many2many table belongs to the module whose uninstall may drop it
    cr.execute(
        """
        UPDATE ir_model_relation rel
           SET module = tax.id
          FROM ir_module_module tax, ir_module_module account
         WHERE tax.name = 'tax' AND account.name = 'account'
           AND rel.module = account.id AND rel.name = ANY(%s)
        """,
        [list(RELATIONS)],
    )
