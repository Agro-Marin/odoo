{
    "name": "Cyprus - Accounting",
    "version": "1.0",
    "category": "Accounting/Localizations/Account Charts",
    "description": """
Basic package for Cyprus that contains the chart of accounts, taxes, tax reports,...
    """,
    "author": "Odoo S.A.",
    "icon": "/account/static/description/l10n.png",
    "license": "LGPL-3",
    "depends": [
        "account",
        "account_edi_ubl_cii",
        "account_vat",
    ],
    "countries": [
        "cy",
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
