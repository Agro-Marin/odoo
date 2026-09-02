{
    "name": "Kuwait - Accounting",
    "version": "1.0",
    "category": "Accounting/Localizations/Account Charts",
    "description": """
This is the base module to manage the accounting chart for Kuwait in Odoo.
==============================================================================
Kuwait accounting basic charts and localization.
Activates:
- Chart of accounts
    """,
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "account",
        "l10n_gcc_invoice",
    ],
    "countries": [
        "kw",
    ],
    "demo": [
        "demo/demo_company.xml",
    ],
    "auto_install": [
        "account",
    ],
}
