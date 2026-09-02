{
    "name": "Portugal - Accounting",
    "version": "1.0",
    "category": "Accounting/Localizations/Account Charts",
    "description": "Portugal - Accounting",
    "author": "Odoo",
    "website": "https://www.odoo.com/documentation/latest/applications/finance/fiscal_localizations.html",
    "icon": "/account/static/description/l10n.png",
    "license": "LGPL-3",
    "depends": [
        "base",
        "account",
        "account_vat",
        "account_edi_ubl_cii",
    ],
    "countries": [
        "pt",
    ],
    "data": [
        "data/account_tax_report.xml",
    ],
    "demo": [
        "demo/demo_company.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "l10n_pt/static/src/helpers/*.js",
        ],
        "web.assets_frontend": [
            "l10n_pt/static/src/helpers/*.js",
        ],
    },
    "auto_install": [
        "account",
    ],
}
