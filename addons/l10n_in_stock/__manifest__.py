# -*- coding: utf-8 -*-
{
    "name": "Indian - Stock Report(GST)",
    "version": "1.0",
    "category": "Accounting/Localizations",
    "description": "GST Stock Report",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "l10n_in",
        "stock",
    ],
    "data": [
        "views/report_stockpicking_operations.xml",
    ],
    "demo": [
        "data/product_demo.xml",
    ],
    "installable": True,
    "auto_install": True,
}
