# -*- coding: utf-8 -*-
{
    "name": "Greece - Accounting",
    "category": "Accounting/Localizations/Account Charts",
    "description": """
This is the base module to manage the accounting chart for Greece.
==================================================================

Greek accounting chart and localization.
    """,
    "author": "P. Christeas, Odoo S.A.",
    "icon": "/account/static/description/l10n.png",
    "license": "LGPL-3",
    "depends": [
        "account",
        "account_iban",
        "account_vat",
        "account_edi_ubl_cii",
    ],
    "countries": [
        "gr",
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
