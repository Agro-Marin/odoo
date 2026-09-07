from odoo.tools.module_data import (
    absorb_readonly_forerunners,
    adopt_xmlids,
    retire_empty_module,
)

FROM_MODULE = "group_readonly"
MODULE = "sale"
ADOPTED = (
    "access_sale_order_sale_readonly",
    "access_sale_order_line_sale_readonly",
    "access_sale_report_sale_readonly",
    "access_account_move_sale_readonly",
    "access_account_move_line_sale_readonly",
    "access_account_partial_reconcile_sale_readonly",
    "access_account_payment_sale_readonly",
)


def migrate(cr, version):
    if not version:
        return
    absorb_readonly_forerunners(cr)
    adopt_xmlids(cr, FROM_MODULE, MODULE, ADOPTED)
    retire_empty_module(cr, FROM_MODULE)
