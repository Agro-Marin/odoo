{
    "name": "Uzbekistan - Accounting",
    "category": "Accounting/Localizations/Account Charts",
    "description": """
Uzbekistan Accounting: Chart of Account.
========================================

Uzbekistan accounting chart and localization.
  """,
    "author": "Odoo S.A.",
    "icon": "/account/static/description/l10n.png",
    "license": "LGPL-3",
    "depends": [
        "account",
        "account_vat",
    ],
    "countries": [
        "uz",
    ],
    "data": [
        "data/account.account.tag.csv",
        "views/res_company_views.xml",
        "views/res_partner_views.xml",
        "views/report_invoice.xml",
        "views/report_templates.xml",
    ],
    "demo": [
        "demo/demo_company.xml",
    ],
    "installable": True,
}
