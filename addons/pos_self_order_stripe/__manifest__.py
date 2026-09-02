# -*- coding: utf-8 -*-
{
    "name": "POS Self Order Stripe",
    "category": "Sales/Point Of Sale",
    "summary": "Addon for the Self Order App that allows customers to pay by Stripe.",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "pos_stripe",
        "pos_self_order",
    ],
    "data": [
        "views/assets_stripe.xml",
    ],
    "assets": {
        "pos_self_order.assets": [
            "pos_self_order_stripe/static/src/**/*",
        ],
        "pos_self_order.assets_tests": [
            "pos_self_order_stripe/static/tests/tours/**/*",
        ],
    },
    "auto_install": True,
}
