{
    "name": "Norway - Accounting",
    "version": "2.1",
    "category": "Accounting/Localizations/Account Charts",
    "description": """This is the module to manage the accounting chart for Norway in Odoo.

Updated for Odoo 9 by Bringsvor Consulting AS <www.bringsvor.com>
""",
    "author": "Rolv R\u00e5en",
    "website": "https://www.odoo.com/documentation/latest/applications/finance/fiscal_localizations.html",
    "icon": "/account/static/description/l10n.png",
    "license": "LGPL-3",
    "depends": [
        "account_iban",
        "account_vat",
        "account",
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
        "no",
    ],
    "data": [
        "data/account_tax_report_data.xml",
        "views/account_tax.xml",
        "views/res_partner_views.xml",
        "views/res_company_views.xml",
    ],
    "demo": [
        "demo/demo_company.xml",
    ],
    "auto_install": [
        "account",
    ],
    "post_init_hook": "_preserve_tag_on_taxes",
}
