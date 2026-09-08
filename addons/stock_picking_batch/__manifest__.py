{
    "name": "Warehouse Management: Batch Transfer",
    "version": "1.1",
    "category": "Supply Chain/Inventory",
    "description": """
This module adds the batch transfer option in warehouse management
==================================================================
    """,
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "stock",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/stock_picking_batch_views.xml",
        "views/stock_picking_type_views.xml",
        "views/stock_move_line_views.xml",
        "views/stock_picking_wave_views.xml",
        "views/stock_picking_views.xml",
        "wizard/stock_picking_to_batch_views.xml",
        "wizard/stock_add_to_wave_views.xml",
        "report/stock_picking_batch_report_views.xml",
        "report/report_picking_batch.xml",
    ],
    "demo": [
        "data/stock_picking_batch_demo.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "stock_picking_batch/static/src/js/stock_picking_many2many_field.js",
            "stock_picking_batch/static/src/scss/*.scss",
        ],
        "web.assets_tests": [
            "stock_picking_batch/static/tests/tours/**/*",
        ],
    },
    "installable": True,
}
