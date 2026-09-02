{
    "name": "T\u00fcrkiye - Accounting",
    "version": "1.3",
    "category": "Accounting/Localizations/Account Charts",
    "description": """
This is the base module to manage the accounting chart for Türkiye in Odoo
==========================================================================

Türkiye accounting basic charts and localizations
-------------------------------------------------
Activates:

- Chart of Accounts
- Taxes
- Tax Report
    """,
    "author": "Odoo S.A., Drysharks Consulting and Trading Ltd.",
    "icon": "/account/static/description/l10n.png",
    "license": "LGPL-3",
    "depends": [
        "account",
    ],
    "countries": [
        "tr",
    ],
    "data": [
        "data/account_tax_report_data.xml",
    ],
    "demo": [
        "demo/demo_company.xml",
    ],
    "auto_install": [
        "account",
    ],
}
