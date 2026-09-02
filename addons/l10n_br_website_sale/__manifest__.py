{
    "name": "Brazil - Website Sale",
    "version": "1.0",
    "category": "Sales/Sales",
    "description": "Bridge Website Sale for Brazil",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "l10n_br",
        "website_sale",
    ],
    "data": [
        "views/templates.xml",
    ],
    "installable": True,
    "auto_install": True,
    "post_init_hook": "_l10n_br_website_sale_post_init_hook",
}
