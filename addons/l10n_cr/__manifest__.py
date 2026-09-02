{
    "name": "Costa Rica - Accounting",
    "category": "Accounting/Localizations/Account Charts",
    "description": """
Chart of accounts for Costa Rica.
=================================

Includes:
---------
    * account.account.template
    * account.tax.template
    * account.chart.template

Everything is in English with Spanish translation. Further translations are welcome,
please go to http://translations.launchpad.net/openerp-costa-rica.
    """,
    "author": "ClearCorp S.A.",
    "website": "https://www.odoo.com/documentation/latest/applications/finance/fiscal_localizations.html",
    "icon": "/account/static/description/l10n.png",
    "license": "LGPL-3",
    "depends": [
        "account",
    ],
    "countries": [
        "cr",
    ],
    "demo": [
        "demo/demo_company.xml",
    ],
    "auto_install": [
        "account",
    ],
    "url": "https://github.com/CLEARCORP/odoo-costa-rica",
}
