{
    "name": "Sale Stock Product Expiry",
    "version": "0.1",
    "category": "Sales/Sales",
    "description": "Modifications to the forecast widget on SO lines to show fresh stock, i.e. ignoring stock to be removed due to expiration.",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "sale_stock",
        "product_expiry",
    ],
    "assets": {
        "web.assets_tests": [
            "sale_stock_product_expiry/static/tests/tours/*.js",
        ],
        "web.assets_backend": [
            "sale_stock_product_expiry/static/src/**/*",
        ],
    },
    "installable": True,
    "auto_install": True,
}
