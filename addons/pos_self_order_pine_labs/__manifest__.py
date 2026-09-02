{
    "name": "POS Self Order Pine Labs",
    "version": "1.0",
    "category": "Sales/Point Of Sale",
    "summary": "An addon for the Self Order App (KIOSK) that allows customers to pay using the Pine Labs POS Terminal.",
    "author": "Odoo IN Pvt Ltd",
    "license": "LGPL-3",
    "depends": [
        "pos_pine_labs",
        "pos_self_order",
    ],
    "assets": {
        "pos_self_order.assets": [
            "pos_self_order_pine_labs/static/src/**/*",
        ],
    },
    "auto_install": True,
}
