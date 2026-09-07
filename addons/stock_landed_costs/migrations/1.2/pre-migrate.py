from odoo.tools.module_data import (
    absorb_readonly_forerunners,
    adopt_xmlids,
    retire_empty_module,
)

FROM_MODULE = "group_readonly"
MODULE = "stock_landed_costs"
ADOPTED = (
    "access_stock_landed_cost_purchase_readonly",
    "access_stock_landed_cost_lines_purchase_readonly",
    "access_stock_valuation_adjustment_lines_purchase_readonly",
)


def migrate(cr, version):
    if not version:
        return
    absorb_readonly_forerunners(cr)
    adopt_xmlids(cr, FROM_MODULE, MODULE, ADOPTED)
    retire_empty_module(cr, FROM_MODULE)
