{
    "name": "Romania - E-Transport",
    "version": "1.0",
    "category": "Accounting/Localizations/EDI",
    "description": """
E-Transport implementation for Romania
    """,
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "stock_delivery",
        "l10n_ro_edi",
        "stock_picking_batch",
    ],
    "data": [
        "data/template_etransport.xml",
        "views/res_config_settings_views.xml",
        "views/stock_picking_views.xml",
        "views/delivery_carrier_views.xml",
        "report/report_deliveryslip.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "l10n_ro_edi_stock/static/src/components/**/*",
        ],
    },
    "installable": True,
}
