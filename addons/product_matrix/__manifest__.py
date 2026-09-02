# -*- coding: utf-8 -*-
{
    "name": "Product Matrix",
    "version": "1.0",
    "category": "Sales/Sales",
    "summary": "Technical module: Matrix Implementation",
    "description": """
Please refer to Sale Matrix or Purchase Matrix for the use of this module.
    """,
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "account",
    ],
    "data": [
        "data/res_groups.xml",
        "views/matrix_templates.xml",
    ],
    "demo": [
        "data/product_matrix_demo.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "product_matrix/static/src/js/matrix_configurator_hook.js",
            "product_matrix/static/src/js/product_matrix_dialog.js",
            "product_matrix/static/src/scss/product_matrix.scss",
            "product_matrix/static/src/xml/**/*",
        ],
    },
}
