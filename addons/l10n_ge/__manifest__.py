{
    "name": "Georgia - Accounting",
    "category": "Accounting/Localizations/Account Charts",
    "summary": "Georgian accounting localization package",
    "description": """
This module provides the basic accounting configuration required to use Odoo Accounting in Georgia, including:
==================================================================================================================
* Georgian chart of accounts
* Tax groups and taxes
* Fiscal Positions
* Georgian VAT report

The module is designed to provide a standard accounting setup for companies operating in Georgia and can be extended further based on specific business or legal requirements.
    """,
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "account",
    ],
    "countries": [
        "GE",
    ],
    "data": [
        "data/account_tax_report_data.xml",
    ],
    "demo": [
        "demo/demo_company.xml",
    ],
}
