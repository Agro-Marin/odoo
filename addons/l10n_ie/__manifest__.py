{
    "name": "Ireland - Accounting",
    "version": "2.1",
    "category": "Accounting/Localizations/Account Charts",
    "description": """
This is the base module to manage the accounting chart for Republic of Ireland in Odoo.
    """,
    "author": "Odoo SA",
    "icon": "/account/static/description/l10n.png",
    "license": "LGPL-3",
    "depends": [
        "account",
        "account_iban",
        "account_vat",
        "account_edi_ubl_cii",
    ],
    "countries": [
        "ie",
    ],
    "data": [
        "data/account.account.tag.csv",
        "data/tax_report-ie.xml",
    ],
    "demo": [
        "demo/demo_company.xml",
    ],
    "auto_install": [
        "account",
    ],
}
