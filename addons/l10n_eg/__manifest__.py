{
    "name": "Egypt - Accounting",
    "version": "1.0",
    "category": "Accounting/Localizations/Account Charts",
    "description": """
Egypt Accounting Module
==============================================================================
Egypt Accounting Basic Charts and Localization.

Activates:

- Chart of Accounts
- Taxes
- VAT Return
- Withholding Tax Report
- Schedule Tax Report
- Other Taxes Report
- Fiscal Positions
    """,
    "author": "Odoo S.A.",
    "website": "https://www.odoo.com/documentation/latest/applications/finance/fiscal_localizations/egypt.html",
    "icon": "/account/static/description/l10n.png",
    "license": "LGPL-3",
    "depends": [
        "account",
    ],
    "countries": [
        "eg",
    ],
    "data": [
        "data/account_tax_report_data.xml",
        "views/account_tax.xml",
    ],
    "demo": [
        "demo/demo_company.xml",
        "demo/demo_partner.xml",
    ],
    "auto_install": [
        "account",
    ],
}
