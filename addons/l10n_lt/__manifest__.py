{
    "name": "Lithuania - Accounting",
    "version": "1.0.0",
    "category": "Accounting/Localizations/Account Charts",
    "description": """
Chart of Accounts (COA) Template for Lithuania's Accounting.

This module also includes:

* List of available banks in Lithuania.
* Tax groups.
* Most common Lithuanian Taxes.
* Fiscal positions.
* Account Tags.
    """,
    "author": "Focusate",
    "website": "https://www.odoo.com/documentation/latest/applications/finance/fiscal_localizations.html",
    "icon": "/account/static/description/l10n.png",
    "license": "LGPL-3",
    "depends": [
        "account",
        "account_edi_ubl_cii",
    ],
    "countries": [
        "lt",
    ],
    "data": [
        "data/account_account_tag_data.xml",
        "data/res_bank_data.xml",
        "data/tax_report_data.xml",
        "views/account_tax.xml",
    ],
    "demo": [
        "demo/demo_company.xml",
    ],
    "installable": True,
    "auto_install": [
        "account",
    ],
}
