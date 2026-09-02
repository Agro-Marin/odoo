{
    "name": "Saudi Arabia - Accounting",
    "version": "2.2",
    "category": "Accounting/Localizations/Account Charts",
    "description": """
Saudi Arabia Accounting Module
===========================================================
Saudi Arabia Accounting Basic Charts and Localization

Activates:

- Chart of Accounts
- Taxes
- VAT Return
- Withholding Return
- Fiscal Positions
""",
    "author": "Odoo S.A.",
    "website": "https://www.odoo.com/documentation/latest/applications/finance/fiscal_localizations/saudi_arabia.html",
    "icon": "/account/static/description/l10n.png",
    "license": "LGPL-3",
    "depends": [
        "l10n_gcc_invoice",
        "account",
        "account_debit_note",
    ],
    "countries": [
        "sa",
    ],
    "data": [
        "data/account_data.xml",
        "data/account_tax_report_data.xml",
        "data/account_tax_report_withholding_data.xml",
        "data/report_paperformat_data.xml",
        "views/account_move_views.xml",
        "views/report_invoice.xml",
        "wizard/account_debit_note.xml",
        "wizard/account_move_reversal_views.xml",
        "views/report_templates_views.xml",
    ],
    "demo": [
        "demo/demo_company.xml",
    ],
    "assets": {
        "web.report_assets_common": [
            "l10n_sa/static/src/scss/styles.scss",
        ],
    },
    "auto_install": [
        "account",
    ],
}
