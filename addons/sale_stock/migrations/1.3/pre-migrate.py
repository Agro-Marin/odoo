from odoo.tools.module_data import rename_in_stored_expressions


def migrate(cr, version):
    if not version:
        return
    rename_in_stored_expressions(
        cr,
        "stock_reference_ids",
        "reference_ids",
        model="sale.order",
    )
