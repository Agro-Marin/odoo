{
    "name": "Slovenian - Accounting",
    "version": "1.1",
    "category": "Accounting/Localizations/Account Charts",
    "description": """
Chart of accounts and taxes for Slovenia.
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
        "si",
    ],
    "data": [
        "data/res_country_data.xml",
        "data/account_account_tag.xml",
        "data/account_tax_report_data.xml",
        "data/account_tax_report_ir_data.xml",
        "data/account_tax_report_pd_data.xml",
        "data/account_tax_report_pr_data.xml",
    ],
    "demo": [
        "demo/demo_company.xml",
    ],
    "auto_install": [
        "account",
    ],
}
