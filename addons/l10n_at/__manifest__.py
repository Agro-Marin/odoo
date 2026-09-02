{
    "name": "Austria - Accounting",
    "version": "3.2.1",
    "category": "Accounting/Localizations/Account Charts",
    "summary": "Austrian Standardized Charts & Tax",
    "description": """

Austrian charts of accounts (Einheitskontenrahmen 2010).
==========================================================

    * Defines the following chart of account templates:
        * Austrian General Chart of accounts 2010
    * Defines templates for VAT on sales and purchases
    * Defines tax templates
    * Defines fiscal positions for Austrian fiscal legislation
    * Defines tax reports U1/U30

    """,
    "author": "WT-IO-IT GmbH, Wolfgang Taferner (https://www.wt-io-it.at)",
    "website": "https://www.odoo.com/documentation/latest/applications/finance/fiscal_localizations.html",
    "icon": "/account/static/description/l10n.png",
    "license": "LGPL-3",
    "depends": [
        "account",
        "account_edi_ubl_cii",
        "account_iban",
        "account_vat",
        "l10n_din5008",
    ],
    "countries": [
        "at",
    ],
    "data": [
        "data/account_account_tag.xml",
        "data/account.account.tag.csv",
        "data/account_tax_report_data.xml",
    ],
    "demo": [
        "demo/demo_company.xml",
    ],
    "auto_install": [
        "account",
    ],
}
