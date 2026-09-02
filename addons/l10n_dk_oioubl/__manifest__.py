{
    "name": "Denmark - E-invoicing",
    "version": "0.1",
    "category": "Accounting/Localizations/EDI",
    "summary": "E-Invoicing, Offentlig Information Online Universal Business Language",
    "description": """
E-invoice implementation for the Denmark
    """,
    "author": "Odoo",
    "license": "LGPL-3",
    "depends": [
        "account_edi_ubl_cii",
        "l10n_dk",
    ],
    "installable": True,
    "auto_install": True,
    "uninstall_hook": "uninstall_hook",
}
