{
    "name": "Finland - Accounting",
    "version": "13.0.2",
    "category": "Accounting/Localizations/Account Charts",
    "description": """
This is the Odoo module to manage the accounting in Finland.
============================================================

After installing this module, you'll have access to:
    * Finnish chart of account
    * Fiscal positions
    * Invoice Payment Reference Types (Finnish Standard Reference & Finnish Creditor Reference (RF))
    * Finnish Reference format for Sale Orders

Set the payment reference type from the Sales Journal.
    """,
    "author": "Avoin.Systems, Tawasta, Vizucom, Sprintit",
    "website": "https://www.odoo.com/documentation/latest/applications/finance/fiscal_localizations.html",
    "icon": "/account/static/description/l10n.png",
    "license": "LGPL-3",
    "depends": [
        "account_iban",
        "account_vat",
        "account",
        "account_edi_ubl_cii",
    ],
    "countries": [
        "fi",
    ],
    "data": [
        "data/account_account_tag_data.xml",
        "data/account_tax_report_line.xml",
        "views/res_company_views.xml",
        "views/res_partner_views.xml",
    ],
    "demo": [
        "demo/demo_company.xml",
    ],
    "installable": True,
    "auto_install": [
        "account",
    ],
}
