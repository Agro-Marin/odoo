{
    "name": "Israel - Accounting",
    "version": "1.1",
    "category": "Accounting/Localizations/Account Charts",
    "description": """
This is the latest basic Israelian localisation necessary to run Odoo in Israel:
================================================================================

This module consists of:
 - Generic Israel Chart of Accounts
 - Taxes and tax report
 - Multiple Fiscal positions
 """,
    "author": "Odoo S.A.",
    "website": "https://www.odoo.com/documentation/latest/applications/finance/fiscal_localizations.html",
    "icon": "/account/static/description/l10n.png",
    "license": "LGPL-3",
    "depends": [
        "account",
    ],
    "countries": [
        "il",
    ],
    "data": [
        "data/account_account_tag.xml",
        "data/account_tax_report_data.xml",
    ],
    "demo": [
        "demo/demo_company.xml",
    ],
    "auto_install": [
        "account",
    ],
}
