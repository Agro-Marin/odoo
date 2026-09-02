{
    "name": "Rwanda - Accounting",
    "version": "1.0",
    "category": "Accounting/Localizations/Account Charts",
    "description": """
    Rwandan localisation containing:
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
        "rw",
    ],
    "data": [
        "data/l10n_rw_chart_data.xml",
        "data/account_tax_report_data.xml",
    ],
    "demo": [
        "demo/demo_company.xml",
    ],
    "auto_install": [
        "account",
    ],
}
