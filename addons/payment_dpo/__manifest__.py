{
    "name": "Payment Provider: DPO",
    "category": "Accounting/Payment Providers",
    "sequence": 350,
    "summary": "A Kenyan payment provider covering several African countries.",
    "description": " ",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "payment",
    ],
    "data": [
        "views/payment_dpo_templates.xml",
        "views/payment_provider_views.xml",
        "data/payment_provider_data.xml",
    ],
    "post_init_hook": "post_init_hook",
    "uninstall_hook": "uninstall_hook",
}
