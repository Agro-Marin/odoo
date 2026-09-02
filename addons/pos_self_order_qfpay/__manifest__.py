{
    "name": "POS Self Order QFPay",
    "category": "Sales/Point Of Sale",
    "summary": "Addon for the Self Order App that allows customers to pay by QFPay.",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "pos_qfpay",
        "pos_self_order",
    ],
    "assets": {
        "pos_self_order.assets": [
            "pos_qfpay/static/src/app/qfpay.js",
            "pos_self_order_qfpay/static/src/**/*",
        ],
        "pos_self_order.assets_tests": [
            "pos_qfpay/static/src/app/qfpay.js",
            "pos_qfpay/static/tests/tours/utils/common.js",
            "pos_self_order_qfpay/static/tests/tours/**/*",
        ],
    },
    "auto_install": True,
}
