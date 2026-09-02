{
    "name": "Malta - Accounting",
    "version": "1.0",
    "category": "Accounting/Localizations/Account Charts",
    "description": """
Malta basic package that contains the chart of accounts, the taxes, tax reports, etc.
    """,
    "author": "Odoo S.A.",
    "website": "https://www.odoo.com/documentation/latest/applications/finance/fiscal_localizations.html",
    "icon": "/account/static/description/l10n.png",
    "license": "LGPL-3",
    "depends": [
        "account",
        "account_vat",
        "account_edi_ubl_cii",
    ],
    "countries": [
        "mt",
    ],
    "data": [
        "data/menuitem_data.xml",
        "data/account_tax_report_data.xml",
    ],
    "demo": [
        "demo/demo_company.xml",
    ],
    "auto_install": [
        "account",
    ],
}
