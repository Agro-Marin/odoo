{
    "name": "Pakistan - Accounting",
    "version": "1.1",
    "category": "Accounting/Localizations/Account Charts",
    "description": """
Pakistan Accounting Module
=======================================================
Pakistan accounting basic charts and localization.

Activates:

- Chart of Accounts
- Taxes
- Tax Report
- Withholding Tax Report
    """,
    "author": "Odoo S.A.",
    "website": "https://www.odoo.com/documentation/latest/applications/finance/fiscal_localizations.html",
    "icon": "/account/static/description/l10n.png",
    "license": "LGPL-3",
    "depends": [
        "account",
    ],
    "countries": [
        "pk",
    ],
    "data": [
        "data/account_tax_vat_report.xml",
        "data/account_tax_wh_report.xml",
    ],
    "demo": [
        "demo/res_partner_demo.xml",
        "demo/demo_company.xml",
    ],
    "auto_install": [
        "account",
    ],
}
