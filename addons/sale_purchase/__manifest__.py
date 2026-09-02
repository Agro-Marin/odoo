{
    "name": "Sale Purchase",
    "version": "1.0",
    "category": "Sales/Sales",
    "summary": "Sale based on service outsourcing.",
    "description": """
Allows the outsourcing of services. This module allows one to sell services provided
by external providers and will automatically generate purchase orders directed to the service seller.
    """,
    "author": "Odoo S.A.",
    "website": "https://www.odoo.com/",
    "license": "LGPL-3",
    "depends": [
        "sale",
        "purchase",
    ],
    "data": [
        "data/mail_templates.xml",
        "views/product_views.xml",
        "views/sale_order_views.xml",
        "views/purchase_order_views.xml",
    ],
    "auto_install": True,
}
