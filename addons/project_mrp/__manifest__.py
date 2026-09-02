{
    "name": "MRP Project",
    "version": "1.0",
    "category": "Services/Project",
    "summary": "Monitor MRP using project",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "mrp",
        "project",
    ],
    "data": [
        "views/mrp_bom_views.xml",
        "views/mrp_production_views.xml",
        "views/project_project_views.xml",
    ],
    "auto_install": True,
}
