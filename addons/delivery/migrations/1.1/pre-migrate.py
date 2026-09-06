from odoo.tools.module_data import adopt_xmlids, retire_empty_module

FROM_MODULE = "group_readonly"
MODULE = "delivery"
ADOPTED = (
    "access_delivery_carrier_sale_readonly",
    "access_delivery_price_rule_sale_readonly",
    "access_delivery_zip_prefix_sale_readonly",
)


def migrate(cr, version):
    if not version:
        return
    adopt_xmlids(cr, FROM_MODULE, MODULE, ADOPTED)
    retire_empty_module(cr, FROM_MODULE)
