# -*- coding: utf-8 -*-
{
    "name": "POS Restaurant Adyen",
    "version": "1.0",
    "category": "Point of Sale",
    "sequence": 6,
    "summary": "Adds American style tipping to Adyen",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "pos_adyen",
        "pos_restaurant",
        "payment_adyen",
    ],
    "data": [
        "views/pos_payment_method_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "pos_restaurant_adyen/static/src/**/*",
        ],
        "web.assets_unit_tests": [
            "pos_restaurant_adyen/static/tests/unit/data/**/*",
        ],
    },
    "auto_install": True,
}
