from odoo.tools.module_data import adopt_xmlids, retire_empty_module

FROM_MODULE = "group_readonly"
MODULE = "sale_mrp"
ADOPTED = (
    "access_mrp_bom_sale_readonly",
    "access_mrp_bom_line_sale_readonly",
    "access_mrp_bom_byproduct_sale_readonly",
    "access_mrp_production_sale_readonly",
    "access_mrp_workorder_sale_readonly",
)


def migrate(cr, version):
    if not version:
        return
    adopt_xmlids(cr, FROM_MODULE, MODULE, ADOPTED)
    retire_empty_module(cr, FROM_MODULE)
