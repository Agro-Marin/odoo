{
    "name": "Project Purchase",
    "version": "1.0",
    "category": "Services/Project",
    "summary": "Monitor purchase in project",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "purchase",
        "project_account",
    ],
    "data": [
        "views/project_project.xml",
        "views/purchase_order.xml",
    ],
    "demo": [
        "data/project_purchase_demo.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "project_purchase/static/src/product_catalog/kanban_record.js",
        ],
    },
    "auto_install": True,
}
