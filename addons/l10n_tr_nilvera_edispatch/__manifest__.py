{
    "name": "T\u00fcrkiye - e-Irsaliye (e-Dispatch)",
    "version": "1.0",
    "category": "Accounting/Localizations",
    "description": "Allows the users to create the UBL 1.2.1 e-Dispatch file",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "l10n_tr_nilvera",
        "stock",
    ],
    "countries": [
        "tr",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/l10n_tr_nilvera_trailer_plate_views.xml",
        "views/res_partner_views.xml",
        "views/stock_picking_views.xml",
        "templates/l10n_tr_nilvera_edispatch.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "l10n_tr_nilvera_edispatch/static/src/views/**/*",
        ],
    },
    "installable": True,
}
