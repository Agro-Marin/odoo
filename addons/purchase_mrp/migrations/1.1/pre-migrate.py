from odoo.tools.module_data import adopt_xmlids, retire_empty_module

FROM_MODULE = "group_readonly"
MODULE = "purchase_mrp"
ADOPTED = (
    "access_mrp_bom_purchase_readonly",
    "access_mrp_bom_line_purchase_readonly",
    "access_mrp_production_purchase_readonly",
)


def migrate(cr, version):
    if not version:
        return
    adopt_xmlids(cr, FROM_MODULE, MODULE, ADOPTED)
    retire_empty_module(cr, FROM_MODULE)
