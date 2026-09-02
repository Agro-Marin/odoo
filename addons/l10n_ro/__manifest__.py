{
    "name": "Romania - Accounting",
    "version": "1.0",
    "category": "Accounting/Localizations/Account Charts",
    "description": """
This is the module to manage the Accounting Chart, VAT structure, Fiscal Position and Tax Mapping.
It also adds the Registration Number for Romania in Odoo.
================================================================================================================

Romanian accounting chart and localization.
    """,
    "author": "Fekete Mihai (NextERP Romania SRL), Odoo S.A.",
    "website": "https://www.odoo.com/documentation/latest/applications/finance/fiscal_localizations/romania.html",
    "icon": "/account/static/description/l10n.png",
    "license": "LGPL-3",
    "depends": [
        "account",
        "account_vat",
        "account_edi_ubl_cii",
    ],
    "countries": [
        "ro",
    ],
    "data": [
        "views/res_partner_view.xml",
        "data/account_tax_report_data.xml",
        "data/res.bank.csv",
    ],
    "demo": [
        "demo/demo_company.xml",
    ],
    "auto_install": [
        "account",
    ],
}
