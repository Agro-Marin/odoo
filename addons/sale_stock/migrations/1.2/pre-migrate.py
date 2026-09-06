from odoo.tools.module_data import adopt_xmlids, retire_empty_module

FROM_MODULE = "group_readonly"
MODULE = "sale_stock"
ADOPTED = (
    "access_stock_picking_sale_readonly",
    "access_stock_move_sale_readonly",
    "access_stock_warehouse_orderpoint_sale_readonly",
    "access_stock_package_type_sale_readonly",
    "access_stock_package_history_sale_readonly",
)


def migrate(cr, version):
    if not version:
        return
    adopt_xmlids(cr, FROM_MODULE, MODULE, ADOPTED)
    retire_empty_module(cr, FROM_MODULE)
