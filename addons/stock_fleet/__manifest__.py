{
    "name": "Stock Transport",
    "version": "1.0",
    "summary": "Stock Transport: Dispatch Management System",
    "description": "Transport Management: organize packs in your fleet, or carriers.",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "stock_picking_batch",
        "fleet",
    ],
    "data": [
        "views/fleet_vehicle_model.xml",
        "views/stock_picking_batch.xml",
        "views/stock_picking_type.xml",
        "views/stock_picking_view.xml",
        "report/report_picking_batch.xml",
        "views/stock_location.xml",
    ],
    "demo": [
        "data/stock_fleet_demo.xml",
    ],
    "post_init_hook": "_enable_dispatch_management",
}
