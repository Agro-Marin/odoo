{
    "name": "Sale Matrix",
    "version": "1.0",
    "category": "Sales/Sales",
    "summary": "Add variants to Sales Order through a grid entry.",
    "description": """
This module allows to fill Sales Order rapidly
by choosing product variants quantity through a Grid Entry.
    """,
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "sale",
        "product_matrix",
    ],
    "data": [
        "views/product_template_views.xml",
        "views/sale_order_views.xml",
        "report/sale_report_templates.xml",
    ],
    "demo": [
        "data/product_matrix_demo.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "sale_product_matrix/static/src/**/*",
        ],
    },
}
