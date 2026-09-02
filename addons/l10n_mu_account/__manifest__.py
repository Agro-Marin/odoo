{
    "name": "Mauritius - Accounting",
    "version": "1.0",
    "category": "Accounting/Localizations/Account Charts",
    "description": """
This is the base module to manage the accounting chart for the Republic of Mauritius in Odoo.
==============================================================================================
    - Chart of accounts
    - Taxes
    - Fiscal positions
    - Default settings
    """,
    "author": "Odoo SA",
    "license": "LGPL-3",
    "depends": [
        "account",
    ],
    "countries": [
        "mu",
    ],
    "data": [
        "data/tax_report-mu.xml",
        "views/report_invoice.xml",
    ],
    "demo": [
        "demo/demo_company.xml",
    ],
    "auto_install": [
        "account",
    ],
}
