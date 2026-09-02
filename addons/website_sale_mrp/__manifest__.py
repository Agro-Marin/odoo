{
    "name": "Kit Availability",
    "version": "1.0",
    "category": "Website/Website",
    "summary": "Manage Kit product inventory & availability",
    "description": """
Manage the inventory of your Kit products and display their availability status in your eCommerce store.
    """,
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "website_sale_stock",
        "sale_mrp",
    ],
    "assets": {
        "web.assets_frontend": [
            "website_sale_mrp/static/src/js/**/*",
        ],
        "web.assets_tests": [
            "website_sale_mrp/static/tests/tours/*",
        ],
    },
    "auto_install": True,
}
