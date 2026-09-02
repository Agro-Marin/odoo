{
    "name": "Sri Lanka - Accounting",
    "version": "1.0",
    "category": "Accounting/Localizations/Account Charts",
    "summary": "Provides accounting localizations for Sri Lanka.",
    "description": """
Sri Lankan Accounting module
============================
- Chart of Accounts
- Fiscal Position
- Taxes & Tax Groups

Forms
=====
- VAT001
- WHT001
    """,
    "author": "Odoo S.A.",
    "website": "https://www.odoo.com/documentation/latest/applications/finance/fiscal_localizations.html",
    "icon": "/account/static/description/l10n.png",
    "license": "LGPL-3",
    "depends": [
        "account",
        "l10n_account_withholding_tax",
    ],
    "countries": [
        "lk",
    ],
    "data": [
        "data/form_vat001.xml",
        "data/form_wht001.xml",
    ],
    "demo": [
        "demo/demo_company.xml",
    ],
    "auto_install": [
        "account",
    ],
}
