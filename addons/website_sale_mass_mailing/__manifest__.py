{
    "name": "Checkout Newsletter",
    "version": "1.0",
    "category": "Website/Website",
    "summary": "Let new customers sign up for a newsletter during checkout",
    "description": """
        Allows anonymous shoppers of your eCommerce to sign up for a newsletter during the checkout
        process.
    """,
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "website_sale",
        "website_mass_mailing",
    ],
    "data": [
        "views/res_config_settings_views.xml",
        "views/templates.xml",
    ],
    "auto_install": True,
}
