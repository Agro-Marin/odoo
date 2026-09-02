# -*- coding: utf-8 -*-
{
    "name": "Indian - Point of Sale",
    "version": "1.0",
    "category": "Accounting/Localizations/Point of Sale",
    "description": "GST Point of Sale",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "l10n_in",
        "point_of_sale",
    ],
    "data": [
        "views/pos_order_line_views.xml",
        "views/res_config_settings_views.xml",
        "data/pos_bill_data.xml",
    ],
    "demo": [
        "data/product_demo.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "l10n_in/static/src/helpers/hsn_summary.js",
            "l10n_in_pos/static/src/**/*",
        ],
        "web.assets_tests": [
            "l10n_in_pos/static/tests/tours/**/*",
        ],
    },
    "auto_install": True,
}
