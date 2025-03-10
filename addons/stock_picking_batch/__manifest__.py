# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    "name": "Warehouse Management: Batch Transfer",
    "version": "1.0",
    "category": "Inventory/Inventory",
    "description": """
        This module adds the batch transfer option in warehouse management
        ==================================================================
    """,
    "depends": ["stock"],
    "data": [
        "security/stock_picking_batch_security.xml",
        "security/ir.model.access.csv",

        "data/stock_picking_batch_data.xml",

        "views/stock_picking_views.xml",
        "views/stock_move_views.xml",
        "views/stock_move_line_views.xml",
        "views/stock_picking_batch_views.xml",
        "views/stock_picking_type_views.xml",

        "wizard/stock_picking_to_batch_views.xml",
        "wizard/stock_add_to_wave_views.xml",

        "report/stock_picking_batch_report_views.xml",
        "report/report_picking_batch.xml",

        "views/stock_picking_batch_menuitem_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "stock_picking_batch/static/src/scss/*.scss",
        ],
        "web.assets_tests": [
            "stock_picking_batch/static/tests/tours/**/*",
        ],
    },
    "demo": [
        "data/stock_picking_batch_demo.xml",
    ],
    "installable": True,
    "license": "LGPL-3",
}
