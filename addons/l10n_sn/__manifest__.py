{
    "name": "S\u00e9n\u00e9gal - Accounting",
    "category": "Accounting/Localizations/Account Charts",
    "description": """
This module implements the taxes for Sénégal.
=================================================================

The Chart of Accounts is from SYSCOHADA.

    """,
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "l10n_syscohada",
        "account",
    ],
    "countries": [
        "sn",
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
