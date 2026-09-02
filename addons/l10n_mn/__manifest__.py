{
    "name": "Mongolia - Accounting",
    "version": "1.1",
    "category": "Accounting/Localizations/Account Charts",
    "description": """
This is the module to manage the accounting chart for Mongolia.
===============================================================

    * the Mongolia Official Chart of Accounts,
    * the Tax Code Chart for Mongolia
    * the main taxes used in Mongolia

Financial requirement contributor: Baskhuu Lodoikhuu. BumanIT LLC
""",
    "author": "BumanIT LLC, Odoo S.A.",
    "website": "https://www.odoo.com/documentation/latest/applications/finance/fiscal_localizations.html",
    "icon": "/account/static/description/l10n.png",
    "license": "LGPL-3",
    "depends": [
        "account",
    ],
    "countries": [
        "mn",
    ],
    "data": [
        "data/account.account.tag.csv",
        "data/vat_report.xml",
    ],
    "demo": [
        "demo/demo_company.xml",
    ],
    "auto_install": [
        "account",
    ],
}
