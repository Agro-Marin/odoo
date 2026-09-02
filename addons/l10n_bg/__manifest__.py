{
    "name": "Bulgaria - Accounting",
    "version": "1.0",
    "category": "Accounting/Localizations/Account Charts",
    "description": """
Chart accounting and taxes for Bulgaria
    """,
    "author": "Odoo S.A.",
    "website": "https://www.odoo.com/documentation/latest/applications/finance/fiscal_localizations.html",
    "icon": "/account/static/description/l10n.png",
    "license": "LGPL-3",
    "depends": [
        "account",
        "account_vat",
    ],
    "countries": [
        "bg",
    ],
    "data": [
        "data/tax_report.xml",
    ],
    "demo": [
        "demo/demo_company.xml",
    ],
    "auto_install": [
        "account",
    ],
}
