{
    "name": "Australia & New Zealand - UBL PINT",
    "version": "1.0",
    "category": "Accounting/Localizations/EDI",
    "description": """
    The UBL PINT e-invoicing format for Australia & New Zealand is based on the Peppol International (PINT) model for Billing.
    """,
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "account_edi_ubl_cii",
    ],
    "countries": [
        "au",
        "nz",
    ],
    "installable": True,
    "uninstall_hook": "uninstall_hook",
}
