{
    "name": "Malaysia - Accounting",
    "version": "1.1",
    "category": "Accounting/Localizations/Account Charts",
    "description": """
This is the base module to manage the accounting chart for Malaysia in Odoo.
==============================================================================
    """,
    "author": "Odoo PS",
    "website": "https://www.odoo.com/documentation/latest/applications/finance/fiscal_localizations.html",
    "icon": "/account/static/description/l10n.png",
    "license": "LGPL-3",
    "depends": [
        "account",
        "account_tax_python",
    ],
    "countries": [
        "my",
    ],
    "data": [
        "data/account_tax_report_data.xml",
        "data/account.account.tag.csv",
        "views/product_template_view.xml",
    ],
    "demo": [
        "demo/demo_company.xml",
    ],
    "auto_install": [
        "account",
    ],
}
