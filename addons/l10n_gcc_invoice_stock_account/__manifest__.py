# -*- coding: utf-8 -*-
{
    "name": "Gulf Cooperation Council WMS Accounting",
    "version": "1.0",
    "category": "Accounting/Localizations",
    "description": """
Adds Arabic as a secondary language for the lots and serial numbers
    """,
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "l10n_gcc_invoice",
        "stock_account",
    ],
    "data": [
        "views/report_invoice.xml",
    ],
    "auto_install": True,
}
