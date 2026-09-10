from odoo.tools.module_data import rename_in_stored_expressions

_RENAMES = (
    ("_set_price_from_bom", "_update_standard_price_from_bom", "product.product"),
    ("_analytic_line_fields", "_get_fields_analytic_line", "mrp.workorder"),
)


def migrate(cr, version):
    if not version:
        return
    for old, new, model in _RENAMES:
        rename_in_stored_expressions(cr, old, new, model=model)
