{
    "name": "Republic of Korea - Accounting",
    "version": "1.0",
    "category": "Accounting/Localizations/Account Charts",
    "description": """
Accounting Module for the Republic of Korea
===========================================
This provides a base chart of accounts and taxes template for use in Odoo.
    """,
    "author": "Odoo S.A.",
    "icon": "/account/static/description/l10n.png",
    "license": "LGPL-3",
    "depends": [
        "account",
    ],
    "countries": [
        "kr",
    ],
    "data": [
        "data/res_country_data.xml",
        "data/general_tax_report.xml",
        "data/simplified_tax_report.xml",
    ],
    "demo": [
        "demo/demo_company.xml",
    ],
    "auto_install": [
        "account",
    ],
}
