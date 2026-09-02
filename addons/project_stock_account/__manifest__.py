{
    "name": "Project Stock Account",
    "version": "1.0",
    "category": "Services/Project",
    "summary": "Handle analytics in Stock pickings with Project",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "stock_account",
        "project_stock",
    ],
    "data": [
        "views/stock_picking_type_views.xml",
    ],
    "auto_install": True,
}
