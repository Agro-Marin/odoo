{
    "name": "Sweden - Accounting",
    "version": "1.1",
    "category": "Accounting/Localizations/Account Charts",
    "description": """
Swedish Accounting
------------------

This is the base module to manage the accounting chart for Sweden in Odoo.
It also includes the invoice OCR payment reference handling.
    """,
    "author": "XCLUDE, Odoo S.A.",
    "website": "https://www.odoo.com/documentation/latest/applications/finance/fiscal_localizations.html",
    "icon": "/account/static/description/l10n.png",
    "license": "LGPL-3",
    "depends": [
        "account",
        "account_vat",
        "account_edi_ubl_cii",
    ],
    "external_dependencies": {
        "python": [
            "python-stdnum",
        ],
        "apt": {
            "python-stdnum": "python3-stdnum",
        },
    },
    "countries": [
        "se",
    ],
    "data": [
        "data/account.account.tag.csv",
        "data/account_tax_report_data.xml",
        "data/res_country_data.xml",
        "views/partner_view.xml",
        "views/account_journal_view.xml",
    ],
    "demo": [
        "demo/demo_company.xml",
    ],
    "auto_install": [
        "account",
    ],
}
