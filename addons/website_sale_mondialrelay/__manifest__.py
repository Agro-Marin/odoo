{
    "name": "eCommerce Mondialrelay Delivery",
    "version": "0.1",
    "category": "Website/Website",
    "summary": "Let's choose Point Relais\u00ae on your ecommerce",
    "description": """
This module allow your customer to choose a Point Relais® and use it as shipping address.
    """,
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "website_sale",
        "delivery_mondialrelay",
    ],
    "data": [
        "views/delivery_carrier_views.xml",
        "views/delivery_form_templates.xml",
        "views/templates.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "website_sale_mondialrelay/static/src/**/*",
        ],
    },
    "auto_install": True,
}
