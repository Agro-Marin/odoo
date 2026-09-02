# -*- coding: utf-8 -*-
{
    "name": "POS Stripe",
    "version": "1.0",
    "category": "Sales/Point of Sale",
    "sequence": 6,
    "summary": "Integrate your POS with a Stripe payment terminal",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "point_of_sale",
        "payment_stripe",
    ],
    "data": [
        "views/pos_payment_method_views.xml",
        "views/assets_stripe.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "pos_stripe/static/src/**/*",
        ],
        "web.assets_unit_tests": [
            "pos_stripe/static/tests/unit/data/**/*",
        ],
    },
    "installable": True,
}
