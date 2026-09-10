from odoo.tools.module_data import rename_in_stored_expressions

_RENAMES = (
    ("_bom_subcontract_find", "_get_subcontract_bom_by_product", "mrp.bom"),
    ("_subcontracted_produce", "_produce_subcontracted_productions", "stock.picking"),
)


def migrate(cr, version):
    if not version:
        return
    for old, new, model in _RENAMES:
        rename_in_stored_expressions(cr, old, new, model=model)
