{
    "name": "Hong Kong - Accounting",
    "version": "1.0",
    "category": "Accounting/Localizations/Account Charts",
    "description": " This is the base module to manage chart of accounting and localization for Hong Kong ",
    "author": "Odoo S.A.",
    "website": "https://www.odoo.com/documentation/latest/applications/finance/fiscal_localizations/hong_kong.html",
    "icon": "/account/static/description/l10n.png",
    "license": "LGPL-3",
    "depends": [
        "account_qr_code_emv",
        "account",
    ],
    "countries": [
        "hk",
    ],
    "data": [
        "data/account_chart_template_data.xml",
        "views/res_bank_views.xml",
    ],
    "demo": [
        "demo/demo_company.xml",
    ],
    "auto_install": [
        "account",
    ],
}
