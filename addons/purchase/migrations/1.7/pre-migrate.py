from odoo.tools.module_data import adopt_xmlids, retire_empty_module

FROM_MODULE = "group_readonly"
MODULE = "purchase"
ADOPTED = (
    "group_purchase_readonly",
    "access_purchase_order_purchase_readonly",
    "access_purchase_order_line_purchase_readonly",
    "access_purchase_report_purchase_readonly",
    "access_purchase_bill_match_purchase_readonly",
    "access_purchase_bill_line_match_purchase_readonly",
    "access_account_move_purchase_readonly",
    "access_account_move_line_purchase_readonly",
    "access_account_partial_reconcile_purchase_readonly",
    "access_account_analytic_line_purchase_readonly",
    "access_account_payment_purchase_readonly",
)


def migrate(cr, version):
    if not version:
        return
    adopt_xmlids(cr, FROM_MODULE, MODULE, ADOPTED)
    retire_empty_module(cr, FROM_MODULE)
