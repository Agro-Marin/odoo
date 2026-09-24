from odoo.tools.module_data import adopt_xmlids

RECORDS = (
    "model_account_payment_term",
    "model_account_payment_term_line",
    "field_res_partner__property_payment_term_id",
    "field_res_partner__property_supplier_payment_term_id",
    "field_res_users__property_payment_term_id",
    "field_res_users__property_supplier_payment_term_id",
    "view_payment_term_search",
    "view_payment_term_tree",
    "view_payment_term_form",
    "view_account_payment_term_kanban",
    "action_payment_term_form",
    "access_account_payment_term_partner_manager",
    "access_account_payment_term_portal",
    "access_account_payment_term_line_partner_manager",
    "account_payment_term_comp_rule",
    "decimal_payment",
    "account_payment_term_immediate",
    "account_payment_term_15days",
    "account_payment_term_21days",
    "account_payment_term_30days",
    "account_payment_term_45days",
    "account_payment_term_end_following_month",
    "account_payment_term_30_days_end_month_the_10",
    "account_payment_term_advance_60days",
    "account_payment_term_30days_early_discount",
    "account_payment_term_90days_on_the_10th",
)

# fiscal_country_codes stays account's: account adds the mixin that declares it
OWN_PATTERN = (
    "^(field|selection|constraint)_{1,2}account_payment_term(_line)?__"
    "(?!fiscal_country_codes$)"
)


def migrate(cr, version):
    if not version:
        return
    # every row changes hands before account loads: an xml id left under
    # account would be orphaned when account stops declaring it, and
    # _process_end would delete the record behind it, and for a field its column
    cr.execute(
        "SELECT name FROM ir_model_data WHERE module = 'account' AND name ~ %s",
        [OWN_PATTERN],
    )
    owned = [name for (name,) in cr.fetchall()]
    adopt_xmlids(cr, "account", "payment_term", (*RECORDS, *owned))
