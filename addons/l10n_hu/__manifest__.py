{
    "name": "Hungary - Accounting",
    "version": "3.0",
    "category": "Accounting/Localizations/Account Charts",
    "description": """
Accounting chart and localization for Hungary
    """,
    "author": "Odoo S.A.",
    "website": "https://www.odoo.com/documentation/latest/applications/finance/fiscal_localizations.html",
    "icon": "/account/static/description/l10n.png",
    "license": "LGPL-3",
    "depends": [
        "account",
        "account_vat",
    ],
    "countries": [
        "hu",
    ],
    "data": [
        "data/account_tax_report_data.xml",
        "data/res.bank.csv",
    ],
    "demo": [
        "demo/demo_company.xml",
    ],
    "auto_install": [
        "account",
    ],
}
