{
    "name": "Morocco - Accounting",
    "category": "Accounting/Localizations/Account Charts",
    "description": """
This is the base module to manage the accounting chart for Morocco.

This module has been built with the help of Caudigef.
""",
    "author": "Odoo SA",
    "icon": "/account/static/description/l10n.png",
    "license": "LGPL-3",
    "depends": [
        "base",
        "account",
    ],
    "countries": [
        "ma",
    ],
    "data": [
        "data/account_tax_report_data.xml",
        "views/res_partner_views.xml",
        "views/res_company_views.xml",
    ],
    "demo": [
        "demo/demo_company.xml",
    ],
    "auto_install": [
        "account",
    ],
}
