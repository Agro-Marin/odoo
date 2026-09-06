from odoo.tools.module_data import (
    adopt_xmlids,
    delete_xmlid_records,
    retire_empty_module,
)

FROM_MODULE = "group_readonly"
MODULE = "stock"
ADOPTED = (
    "group_stock_readonly",
    "access_stock_picking_stock_readonly",
    "access_stock_lot_stock_readonly",
    "access_stock_move_stock_readonly",
    "access_stock_scrap_stock_readonly",
    "access_stock_scrap_reason_tag_stock_readonly",
    "access_stock_warehouse_orderpoint_stock_readonly",
    "access_stock_package_type_stock_readonly",
    "access_stock_traceability_report_stock_readonly",
    "access_stock_quantity_history_stock_readonly",
    "access_stock_rules_report_stock_readonly",
    "access_stock_package_history_stock_readonly",
)
DROPPED = (
    "view_stock_picking_form_readonly",
    "view_stock_quant_inventory_readonly",
)


def migrate(cr, version):
    if not version:
        return
    adopt_xmlids(cr, FROM_MODULE, MODULE, ADOPTED)
    delete_xmlid_records(cr, FROM_MODULE, DROPPED)
    retire_empty_module(cr, FROM_MODULE)
