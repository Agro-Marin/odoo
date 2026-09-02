{
    "name": "Project Stock",
    "version": "1.0",
    "category": "Services/Project",
    "summary": "Link Stock pickings to Project",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "stock",
        "project",
    ],
    "data": [
        "views/stock_picking_views.xml",
        "views/project_project_views.xml",
    ],
    "auto_install": True,
}
