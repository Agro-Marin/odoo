{
    "name": "Democratic Republic of the Congo - Accounting",
    "category": "Accounting/Localizations/Account Charts",
    "description": """
This module implements the tax for the Democratic Republic of the Congo.
===========================================================================

The Chart of Accounts is from SYSCOHADA.

    """,
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "l10n_syscohada",
        "account",
    ],
    "countries": [
        "cd",
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
