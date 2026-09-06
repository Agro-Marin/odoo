from odoo.tools.module_data import adopt_xmlids, retire_empty_module

FROM_MODULE = "group_readonly"
MODULE = "sales_team"
ADOPTED = (
    "group_sale_readonly",
    "access_crm_tag_sale_readonly",
)


def migrate(cr, version):
    if not version:
        return
    adopt_xmlids(cr, FROM_MODULE, MODULE, ADOPTED)
    retire_empty_module(cr, FROM_MODULE)
