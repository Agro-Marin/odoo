# -*- encoding: utf-8 -*-

{
    "name": "Tunisia - Accounting",
    "version": "1.0",
    "category": "Accounting/Localizations/Account Charts",
    "description": """
This is the module to manage the accounting chart for Tunisia in Odoo.
=======================================================================
""",
    "author": "Odoo S.A.",
    "icon": "/account/static/description/l10n.png",
    "license": "LGPL-3",
    "depends": [
        "account",
    ],
    "countries": [
        "tn",
    ],
    "data": [
        "data/tax_report.xml",
    ],
    "demo": [
        "demo/demo_company.xml",
    ],
    "auto_install": [
        "account",
    ],
}
