{
    "name": "Ukraine - Accounting",
    "version": "1.4",
    "category": "Accounting/Localizations/Account Charts",
    "description": """
Ukraine - Chart of accounts.
============================
    """,
    "author": "ERP Ukraine (https://erp.co.ua)",
    "website": "https://www.odoo.com/documentation/latest/applications/finance/fiscal_localizations.html",
    "icon": "/account/static/description/l10n.png",
    "license": "LGPL-3",
    "depends": [
        "account",
    ],
    "countries": [
        "ua",
    ],
    "data": [
        "data/account_account_tag_data.xml",
    ],
    "demo": [
        "demo/demo_company.xml",
    ],
    "auto_install": [
        "account",
    ],
}
