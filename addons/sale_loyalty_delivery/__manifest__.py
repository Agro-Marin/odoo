{
    "name": "Sale Loyalty - Delivery",
    "category": "Sales/Sales",
    "summary": "Adds free shipping mechanism in sales orders",
    "description": "Integrate free shipping in sales orders.",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "sale_loyalty",
        "delivery",
    ],
    "data": [
        "views/loyalty_reward_views.xml",
    ],
    "auto_install": True,
}
