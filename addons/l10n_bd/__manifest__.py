{
    "name": "Bangladesh - Accounting",
    "version": "1.0",
    "category": "Accounting/Localizations/Account Charts",
    "description": """
This is the base module to manage the accounting chart for Bangladesh in Odoo
==============================================================================

Bangladesh accounting basic charts and localization.

Activates:

- Chart of accounts
- Taxes
- Tax report
""",
    "author": "Odoo S.A.",
    "website": "https://www.odoo.com/documentation/latest/applications/finance/fiscal_localizations.html",
    "icon": "/account/static/description/l10n.png",
    "license": "LGPL-3",
    "depends": [
        "account",
    ],
    "countries": [
        "bd",
    ],
    "data": [
        "data/account.account.tag.csv",
        "data/account_tax_report_data.xml",
        "views/menu_items.xml",
    ],
    "demo": [
        "demo/demo_company.xml",
    ],
    "auto_install": [
        "account",
    ],
}
