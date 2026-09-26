from odoo.tools.module_data import rename_field, rename_in_stored_expressions

RENAMES = (
    ("purchase.requisition", "vendor_id", "partner_id"),
    ("purchase.requisition", "requisition_type", "agreement_type"),
    ("purchase.requisition", "purchase_ids", "order_ids"),
    ("purchase.requisition.line", "requisition_id", "agreement_id"),
    ("purchase.order", "requisition_id", "agreement_id"),
    ("purchase.order", "requisition_type", "agreement_type"),
)


def migrate(cr, version):
    if not version:
        return
    for model, old, new in RENAMES:
        rename_field(cr, model, old, new)
        rename_in_stored_expressions(cr, old, new, model=model)
