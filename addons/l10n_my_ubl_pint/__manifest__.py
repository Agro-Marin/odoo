{
    "name": "Malaysia - UBL PINT",
    "version": "1.0",
    "category": "Accounting/Localizations/EDI",
    "description": """
    The UBL PINT e-invoicing format for Malaysia is based on the Peppol International (PINT) model for Billing.
    """,
    "author": "Odoo S.A.",
    "icon": "/account/static/description/l10n.png",
    "license": "LGPL-3",
    "depends": [
        "account_edi_ubl_cii",
    ],
    "countries": [
        "my",
    ],
    "data": [
        "views/report_invoice.xml",
        "views/res_company_view.xml",
        "views/res_partner_view.xml",
    ],
    "installable": True,
    "uninstall_hook": "uninstall_hook",
}
