{
    "name": "Singapore - Accounting",
    "version": "2.2",
    "category": "Accounting/Localizations/Account Charts",
    "description": """
Singapore accounting chart and localization.
=======================================================

This module add, for accounting:
 - The Chart of Accounts of Singapore
 - Field UEN (Unique Entity Number) on company and partner
 - Field PermitNo and PermitNoDate on invoice

    """,
    "author": "Tech Receptives",
    "website": "https://www.odoo.com/documentation/latest/applications/finance/fiscal_localizations/singapore.html",
    "icon": "/account/static/description/l10n.png",
    "license": "LGPL-3",
    "depends": [
        "account_qr_code_emv",
        "account",
    ],
    "countries": [
        "sg",
    ],
    "data": [
        "data/l10n_sg_chart_data.xml",
        "data/account_tax_report_data.xml",
        "views/account_invoice_view.xml",
        "views/res_bank_views.xml",
        "views/res_company_view.xml",
        "views/res_partner_view.xml",
    ],
    "demo": [
        "demo/demo_company.xml",
    ],
    "auto_install": [
        "account",
    ],
    "post_init_hook": "_preserve_tag_on_taxes",
}
