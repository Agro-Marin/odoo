{
    "name": "Sale Project - Sale Stock",
    "version": "1.0",
    "category": "Sales",
    "summary": "Adds a full traceability of inventory operations on the profitability report.",
    "description": "Adds a full traceability of inventory operations on the profitability report.",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "sale_project",
        "sale_stock",
        "project_stock_account",
    ],
    "data": [
        "views/stock_move_views.xml",
    ],
    "auto_install": True,
}
