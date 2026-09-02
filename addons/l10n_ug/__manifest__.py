# -*- coding: utf-8 -*-

{
    "name": "Uganda - Accounting",
    "version": "1.0.0",
    "category": "Accounting/Localizations/Account Charts",
    "description": """
This is the basic Ugandian localisation necessary to run Odoo in UG:
================================================================================
    - Chart of accounts
    - Taxes
    - Fiscal positions
    - Default settings
    - Tax report
    """,
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "account",
    ],
    "countries": [
        "ug",
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
