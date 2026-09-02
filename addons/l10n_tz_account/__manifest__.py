{
    "name": "Tanzania - Accounting",
    "version": "1.0",
    "category": "Accounting/Localizations/Account Charts",
    "description": """
    Tanzanian localisation containing:
    - COA
    - Taxes
    - Tax report
    - Fiscal position
    """,
    "author": "Odoo S.A.",
    "icon": "/account/static/description/l10n.png",
    "license": "LGPL-3",
    "depends": [
        "account",
    ],
    "countries": [
        "tz",
    ],
    "data": [
        "data/l10n_tz_chart_data.xml",
        "data/account_tax_report_data.xml",
    ],
    "demo": [
        "demo/demo_company.xml",
    ],
    "auto_install": [
        "account",
    ],
}
