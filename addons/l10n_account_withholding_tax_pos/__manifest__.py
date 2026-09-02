{
    "name": "Withholding Tax on Payment - PoS",
    "version": "1.0",
    "category": "Accounting/Localizations",
    "description": "Add support for the withholding tax module in the PoS.",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "l10n_account_withholding_tax",
        "point_of_sale",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "l10n_account_withholding_tax/static/src/helpers/*.js",
        ],
    },
    "auto_install": True,
}
