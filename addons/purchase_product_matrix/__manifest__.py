{
    "name": "Purchase Matrix",
    "version": "1.0",
    "category": "Supply Chain/Purchase",
    "summary": "Add variants to your purchase orders through an Order Grid Entry.",
    "description": """
This module allows to fill Purchase Orders rapidly
by choosing product variants quantity through a Grid Entry.
    """,
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "purchase",
        "product_matrix",
    ],
    "data": [
        "views/purchase_views.xml",
        "reports/purchase_quotation_templates.xml",
        "reports/purchase_order_templates.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "purchase_product_matrix/static/src/**/*",
        ],
        "web.assets_tests": [
            "purchase_product_matrix/static/tests/tours/**/*",
        ],
    },
}
