{
    "name": "Singapore - UBL PINT",
    "version": "1.0",
    "category": "Accounting/Localizations/EDI",
    "description": """
    The UBL PINT e-invoicing format for Singapore is based on the Peppol International (PINT) model for Billing.
    """,
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "account_edi_ubl_cii",
    ],
    "countries": [
        "sg",
    ],
    "installable": True,
    "uninstall_hook": "uninstall_hook",
}
