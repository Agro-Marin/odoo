# coding: utf-8
{
    "name": "Brazil - Sale",
    "version": "1.0",
    "category": "Sales/Sales",
    "description": "Sale modifications for Brazil",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "l10n_br",
        "sale",
    ],
    "data": [
        "views/sale_portal_templates.xml",
        "report/sale_order_templates.xml",
        "report/report_invoice_templates.xml",
    ],
    "installable": True,
    "auto_install": True,
}
