{
    "name": "Bahrain - Accounting",
    "version": "1.0",
    "category": "Accounting/Localizations/Account Charts",
    "description": """
This is the base module to manage the accounting chart for Bahrain in Odoo.
===========================================================================
Bahrain accounting basic charts and localization.

Activates:
 - Chart of Accounts
 - Taxes
 - Tax reports
 - Fiscal Positions
 - States
    """,
    "author": "Odoo S.A.",
    "icon": "/account/static/description/l10n.png",
    "license": "LGPL-3",
    "depends": [
        "account",
        "l10n_gcc_invoice",
    ],
    "countries": [
        "bh",
    ],
    "data": [
        "data/tax_report_full.xml",
        "data/tax_report_simplified.xml",
        "data/res.country.state.csv",
    ],
    "demo": [
        "demo/demo_company.xml",
    ],
    "auto_install": [
        "account",
    ],
}
