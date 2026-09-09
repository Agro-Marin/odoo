from odoo.db.schema import drop_view_if_exists


def migrate(cr, version):
    if not version:
        return
    drop_view_if_exists(cr, "customer_delay_report")
