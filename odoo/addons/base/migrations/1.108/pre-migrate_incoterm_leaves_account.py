from odoo.tools.module_data import adopt_xmlids

RECORDS = (
    "model_account_incoterms",
    "access_account_incoterms_all",
    "view_incoterms_tree",
    "account_incoterms_form",
    "account_incoterms_view_search",
    "action_incoterms_tree",
    "incoterm_EXW",
    "incoterm_FCA",
    "incoterm_FAS",
    "incoterm_FOB",
    "incoterm_CFR",
    "incoterm_CIF",
    "incoterm_CPT",
    "incoterm_CIP",
    "incoterm_DAP",
    "incoterm_DPU",
    "incoterm_DDP",
)


def migrate(cr, version):
    if not version:
        return
    # the rows change hands before account loads: an xml id left under account
    # would be orphaned when account stops declaring it, and _process_end would
    # delete the record behind it, and for a field its column
    cr.execute(
        "SELECT name FROM ir_model_data"
        " WHERE module = 'account' AND name ~ '^field_account_incoterms__'"
    )
    fields = [name for (name,) in cr.fetchall()]
    adopt_xmlids(cr, "account", "incoterm", (*RECORDS, *fields))
