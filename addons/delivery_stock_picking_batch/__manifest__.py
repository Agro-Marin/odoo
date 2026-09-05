{
    "name": "Delivery Stock Picking Batch",
    "version": "1.0",
    "category": "Supply Chain/Inventory",
    "summary": "Batch Transfer, Carrier",
    "description": """
This module makes the link between the batch pickings and carrier applications.

Allows to prepare batches depending on their carrier
""",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "stock_delivery",
        "stock_picking_batch",
    ],
    "data": [
        "views/stock_picking_type_views.xml",
        "views/stock_picking_batch_views.xml",
    ],
    "installable": True,
    "auto_install": True,
}
