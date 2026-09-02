{
    "name": "Zambia - Accounting",
    "version": "1.0.0",
    "category": "Accounting/Localizations/Account Charts",
    "description": """
This is the basic Zambian localization necessary to run Odoo in ZM:
================================================================================
    - Chart of Accounts
    - Taxes
    - Fiscal Positions
    - Default Settings
    """,
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "account",
    ],
    "countries": [
        "zm",
    ],
    "data": [
        "data/account_tax_report_data.xml",
        "views/report_invoice.xml",
    ],
    "demo": [
        "demo/demo_company.xml",
    ],
    "auto_install": [
        "account",
    ],
}
