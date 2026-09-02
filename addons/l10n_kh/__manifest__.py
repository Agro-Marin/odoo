{
    "name": "Cambodia - Accounting",
    "version": "1.0",
    "category": "Accounting/Localizations/Account Charts",
    "description": """
    Chart Of Account and Taxes for Cambodia.
    """,
    "author": "Odoo S.A.",
    "website": "https://www.odoo.com/documentation/latest/applications/finance/fiscal_localizations.html",
    "icon": "/account/static/description/l10n.png",
    "license": "LGPL-3",
    "depends": [
        "account_qr_code_emv",
        "l10n_account_withholding_tax",
    ],
    "countries": [
        "kh",
    ],
    "data": [
        "data/form_t7001.xml",
        "data/form_wt003.xml",
        "views/res_bank_views.xml",
    ],
    "demo": [
        "demo/demo_company.xml",
    ],
}
