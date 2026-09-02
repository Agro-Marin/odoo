{
    "name": "Italy - Sale E-invoicing",
    "version": "1.0",
    "category": "Accounting/Localizations/EDI",
    "description": "Sale modifications for Italy E-invoicing",
    "author": "Odoo S.A.",
    "website": "https://www.odoo.com/documentation/latest/applications/finance/fiscal_localizations/italy.html",
    "license": "LGPL-3",
    "depends": [
        "l10n_it_edi",
        "sale",
    ],
    "data": [
        "views/sale_order_views.xml",
    ],
    "installable": True,
    "auto_install": True,
}
