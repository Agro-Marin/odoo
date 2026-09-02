{
    "name": "United States - Accounting",
    "version": "1.0",
    "category": "Accounting/Localizations/Account Charts",
    "description": """
    """,
    "author": "Odoo S.A.",
    "website": "https://www.odoo.com/documentation/latest/applications/finance/fiscal_localizations.html",
    "icon": "/account/static/description/l10n.png",
    "license": "LGPL-3",
    "depends": [
        "l10n_us",
        "account",
    ],
    "countries": [
        "us",
    ],
    "data": [
        "views/res_bank_views.xml",
        "data/tax_report.xml",
        "data/uom_data.xml",
    ],
    "demo": [
        "demo/demo_company.xml",
    ],
    "installable": True,
    "auto_install": [
        "account",
    ],
}
