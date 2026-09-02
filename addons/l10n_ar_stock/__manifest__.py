{
    "name": "Argentinean - Stock",
    "version": "1.0",
    "category": "Accounting/Localizations",
    "description": "Argentinean - Stock",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "l10n_ar",
        "stock_account",
    ],
    "data": [
        "data/mail_template_data.xml",
        "views/stock_picking_type_views.xml",
        "views/stock_picking_views.xml",
        "views/report_delivery_guide.xml",
    ],
    "installable": True,
    "auto_install": True,
}
