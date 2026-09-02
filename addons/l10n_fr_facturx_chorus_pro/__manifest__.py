# -*- coding: utf-8 -*-
{
    "name": "France - BIS3 integration for Chorus Pro",
    "version": "1.0",
    "category": "Accounting/Localizations/EDI",
    "description": """
Add support to fill three fields used when using Chorus Pro, especially when invoicing public services.
""",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "account",
        "account_edi_ubl_cii",
        "l10n_fr_account",
    ],
    "countries": [
        "fr",
    ],
    "data": [
        "views/account_move_views.xml",
        "views/report_invoice.xml",
    ],
}
