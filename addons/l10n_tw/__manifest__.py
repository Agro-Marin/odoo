{
    "name": "Taiwan - Accounting",
    "version": "1.0",
    "category": "Accounting/Localizations/Account Charts",
    "description": """
This is the base module to manage the accounting chart for Taiwan in Odoo.
==============================================================================
    """,
    "author": "Odoo PS",
    "website": "https://www.odoo.com/documentation/latest/applications/finance/fiscal_localizations.html",
    "icon": "/account/static/description/l10n.png",
    "license": "LGPL-3",
    "depends": [
        "account",
        "partner_address_extended",
    ],
    "countries": [
        "tw",
    ],
    "data": [
        "data/res_currency_data.xml",
        "data/res_country_data.xml",
        "data/res.city.csv",
    ],
    "demo": [
        "demo/demo_company.xml",
    ],
    "auto_install": [
        "account",
    ],
}
