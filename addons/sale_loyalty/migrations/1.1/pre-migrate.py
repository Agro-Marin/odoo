from odoo.tools.module_data import (
    absorb_readonly_forerunners,
    adopt_xmlids,
    retire_empty_module,
)

FROM_MODULE = "group_readonly"
MODULE = "sale_loyalty"
ADOPTED = (
    "access_loyalty_card_sale_readonly",
    "access_loyalty_program_sale_readonly",
    "access_loyalty_rule_sale_readonly",
    "access_loyalty_reward_sale_readonly",
    "access_loyalty_history_sale_readonly",
    "access_loyalty_mail_sale_readonly",
    "access_sale_order_coupon_points_sale_readonly",
)


def migrate(cr, version):
    if not version:
        return
    absorb_readonly_forerunners(cr)
    adopt_xmlids(cr, FROM_MODULE, MODULE, ADOPTED)
    retire_empty_module(cr, FROM_MODULE)
