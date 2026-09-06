from odoo.tools.module_data import adopt_xmlids, retire_empty_module

FROM_MODULE = "group_readonly"
MODULE = "purchase_stock"
ADOPTED = (
    "access_vendor_delay_report_purchase_readonly",
    "access_stock_picking_purchase_readonly",
    "access_stock_move_purchase_readonly",
    "access_stock_warehouse_orderpoint_purchase_readonly",
    "access_stock_lot_purchase_readonly",
)


def migrate(cr, version):
    if not version:
        return
    adopt_xmlids(cr, FROM_MODULE, MODULE, ADOPTED)
    retire_empty_module(cr, FROM_MODULE)
