{
    "name": "Saudi Arabia - Withholding Tax",
    "category": "Accounting/Localizations/Account Charts",
    "description": """
Saudi Arabia Withholding Tax Module

Force the installation of the Withholding Tax on Payment module
""",
    "author": "Odoo S.A.",
    "website": "https://www.odoo.com/documentation/master/applications/finance/fiscal_localizations/saudi_arabia.html",
    "icon": "/account/static/description/l10n.png",
    "license": "LGPL-3",
    "depends": [
        "l10n_account_withholding_tax",
        "l10n_sa",
    ],
    "auto_install": [
        "l10n_sa",
    ],
}
