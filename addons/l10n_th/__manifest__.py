{
    "name": "Thailand - Accounting",
    "version": "2.0",
    "category": "Accounting/Localizations/Account Charts",
    "description": """
Chart of Accounts for Thailand.
===============================

Thai accounting chart and localization.
    """,
    "author": "Almacom (http://almacom.co.th/)",
    "website": "https://www.odoo.com/documentation/latest/applications/finance/fiscal_localizations/thailand.html",
    "icon": "/account/static/description/l10n.png",
    "license": "LGPL-3",
    "depends": [
        "account_qr_code_emv",
        "account",
    ],
    "countries": [
        "th",
    ],
    "data": [
        "data/account_tax_report_data.xml",
        "views/report_invoice.xml",
    ],
    "demo": [
        "demo/demo_company.xml",
    ],
    "auto_install": [
        "account",
    ],
    "post_init_hook": "_preserve_tag_on_taxes",
}
