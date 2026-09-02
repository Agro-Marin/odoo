{
    "name": "Colombia - Accounting",
    "version": "1.0",
    "category": "Accounting/Localizations/Account Charts",
    "description": "Colombian Accounting and Tax Preconfiguration",
    "author": "David Arnold (XOE Solutions)",
    "website": "https://www.odoo.com/documentation/latest/applications/finance/fiscal_localizations/colombia.html",
    "icon": "/account/static/description/l10n.png",
    "license": "LGPL-3",
    "depends": [
        "account_debit_note",
        "l10n_latam_base",
        "account",
    ],
    "countries": [
        "co",
    ],
    "data": [
        "data/account_chart_template_data.xml",
        "data/l10n_latam.identification.type.csv",
    ],
    "demo": [
        "demo/demo_company.xml",
    ],
    "auto_install": [
        "account",
    ],
}
