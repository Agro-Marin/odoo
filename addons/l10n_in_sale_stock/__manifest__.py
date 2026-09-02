# -*- coding: utf-8 -*-
{
    "name": "India Sales and Warehouse Management",
    "version": "0.1",
    "category": "Accounting/Localizations/Sale",
    "summary": "Get warehouse address if the invoice is created from Sale Order",
    "description": """
Get the warehouse address if the invoice is created from the Sale Order
In Indian EDI we send shipping address details if available

So this module is to get the warehouse address if the invoice is created from Sale Order
    """,
    "author": "Odoo S.A.",
    "website": "https://www.odoo.com",
    "license": "LGPL-3",
    "depends": [
        "l10n_in_sale",
        "l10n_in_stock",
        "sale_stock",
    ],
    "auto_install": True,
}
