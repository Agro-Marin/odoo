{
    "name": "Bolivia - Accounting",
    "version": "2.0",
    "category": "Accounting/Localizations/Account Charts",
    "description": """
Bolivian accounting chart and tax localization.

Plan contable boliviano e impuestos de acuerdo a disposiciones vigentes

    """,
    "author": "Odoo / Cubic ERP",
    "website": "https://www.odoo.com/documentation/latest/applications/finance/fiscal_localizations.html",
    "icon": "/account/static/description/l10n.png",
    "license": "LGPL-3",
    "depends": [
        "account",
    ],
    "countries": [
        "bo",
    ],
    "data": [
        "data/account_tax_report_data.xml",
    ],
    "demo": [
        "demo/demo_company.xml",
    ],
    "auto_install": [
        "account",
    ],
}
