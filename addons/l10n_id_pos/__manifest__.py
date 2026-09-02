{
    "name": "Indonesia - Point of Sale",
    "version": "1.0",
    "category": "Accounting/Localizations/Point of Sale",
    "description": "Indonesian Point of Sale",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "l10n_id",
        "point_of_sale",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "l10n_id_pos/static/src/**/*",
        ],
        "web.assets_tests": [
            "l10n_id_pos/static/tests/**/*",
        ],
    },
    "auto_install": True,
}
