{
    "name": "Payment Provider: Demo",
    "version": "2.0",
    "category": "Accounting/Accounting",
    "sequence": 350,
    "summary": "A payment provider for running fake payment flows for demo purposes.",
    "description": " ",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "payment",
    ],
    "data": [
        "views/payment_demo_templates.xml",
        "views/payment_provider_views.xml",
        "views/payment_token_views.xml",
        "views/payment_transaction_views.xml",
        "data/payment_method_data.xml",
        "data/payment_provider_data.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "payment_demo/static/src/interactions/**/*",
        ],
    },
    "post_init_hook": "post_init_hook",
    "uninstall_hook": "uninstall_hook",
}
