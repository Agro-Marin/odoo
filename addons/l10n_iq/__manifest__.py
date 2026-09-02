{
    "name": "Iraq - Accounting",
    "version": "1.0",
    "category": "Accounting/Localizations/Account Charts",
    "description": """
This is the base module to manage the accounting chart for Iraq in Odoo.
==============================================================================
Iraq accounting basic charts and localization.
Activates:
- Chart of accounts
- Taxes
    """,
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "account",
    ],
    "countries": [
        "iq",
    ],
    "demo": [
        "demo/demo_company.xml",
    ],
    "auto_install": [
        "account",
    ],
}
