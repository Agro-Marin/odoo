{
    "name": "POS Self Order Razorpay",
    "version": "1.0",
    "category": "Sales/Point Of Sale",
    "summary": "Addon for the Self Order App that allows customers to pay by Razorpay POS Terminal.",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "pos_razorpay",
        "pos_self_order",
    ],
    "assets": {
        "pos_self_order.assets": [
            "pos_self_order_razorpay/static/**/*",
        ],
    },
    "auto_install": True,
}
