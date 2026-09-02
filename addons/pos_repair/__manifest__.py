{
    "name": "POS - Repair",
    "category": "Technical",
    "summary": "Link module between Point of Sale and Repair",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "point_of_sale",
        "repair",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "pos_repair/static/src/**/*",
        ],
        "web.assets_tests": [
            "pos_repair/static/tests/tours/**/*",
        ],
    },
    "installable": True,
    "auto_install": True,
}
