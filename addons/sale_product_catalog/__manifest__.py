{
    "name": "Products catalog for sale orders",
    "description": """
This module introduces a catalog view that allows users to select
products in a faster and easier way than before, both in desktop and
mobile view.
    """,
    "category": "Sale",
    "version": "1.0",
    "depends": ["sale"],
    "data": [
        "views/product_product_views.xml",
        "views/sale_order_views.xml",
    ],
    # only loaded in demonstration mode
    "demo": [],
}
