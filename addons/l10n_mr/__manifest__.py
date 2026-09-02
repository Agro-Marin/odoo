{
    "name": "Mauritania - Accounting",
    "version": "1.0",
    "category": "Accounting/Localizations/Account Charts",
    "description": """
Mauritania basic package that contains the chart of accounts, the taxes, tax reports, etc.
    """,
    "author": "Odoo S.A.",
    "website": "https://www.odoo.com/documentation/master/applications/finance/fiscal_localizations.html",
    "icon": "/account/static/description/l10n.png",
    "license": "LGPL-3",
    "depends": [
        "account",
        "account_vat",
    ],
    "countries": [
        "mr",
    ],
    "data": [
        "data/account_tax_report_data.xml",
    ],
    "demo": [
        "demo/demo_company.xml",
    ],
}
