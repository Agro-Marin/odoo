# -*- coding: utf-8 -*-
{
    "name": "Colombian - Point of Sale",
    "version": "1.0",
    "category": "Accounting/Localizations/Point of Sale",
    "description": "Colombian - Point of Sale",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "l10n_co",
        "point_of_sale",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "l10n_co_pos/static/src/**/*",
        ],
    },
    "auto_install": True,
}
