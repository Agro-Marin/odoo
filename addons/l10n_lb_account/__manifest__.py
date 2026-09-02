{
    "name": "Lebanon - Accounting",
    "version": "1.0",
    "category": "Accounting/Localizations/Account Charts",
    "description": """
This is the base module to manage the accounting chart for Lebanon in Odoo.
==============================================================================
Lebanon accounting basic charts,taxes and localization.
Activates:
* Chart of Accounts
* Taxes
* Fiscal Positions
    """,
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "account",
    ],
    "countries": [
        "lb",
    ],
    "data": [
        "data/res.country.state.csv",
    ],
    "demo": [
        "demo/demo_company.xml",
    ],
    "auto_install": [
        "account",
    ],
}
