{
    "name": "Jordan - Accounting",
    "version": "1.0",
    "category": "Accounting/Localizations/Account Charts",
    "description": """
This is the base module to manage the accounting chart for Jordan in Odoo.
==============================================================================

Jordan accounting basic charts and localization.

Activates:

- Chart of accounts

- Taxes

- Tax report

- Fiscal positions
    """,
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "account",
    ],
    "countries": [
        "jo",
    ],
    "data": [
        "data/account_tax_report_data.xml",
    ],
    "demo": [
        "demo/demo_company.xml",
        "demo/demo_partner.xml",
    ],
    "auto_install": [
        "account",
    ],
}
