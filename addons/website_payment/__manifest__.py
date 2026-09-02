{
    "name": "Website Payment",
    "version": "1.0",
    "category": "Website/Website",
    "summary": "Payment integration with website",
    "description": """
This is a bridge module that adds multi-website support for payment providers.
    """,
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "website",
        "account_payment_provider",
        "portal",
    ],
    "data": [
        "data/mail_templates.xml",
        "views/payment_form_templates.xml",
        "views/payment_provider.xml",
        "views/res_config_settings_views.xml",
        "views/snippets/snippets.xml",
        "views/snippets/s_donation.xml",
        "views/snippets/s_supported_payment_methods.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "website_payment/static/src/interactions/*",
            "website_payment/static/src/snippets/**/*.js",
            (
                "remove",
                "website_payment/static/src/snippets/**/*.edit.js",
            ),
        ],
        "website.assets_inside_builder_iframe": [
            "website_payment/static/src/**/*.edit.js",
        ],
        "web.assets_tests": [
            "website_payment/static/tests/tours/donation.js",
        ],
        "web.assets_unit_tests": [
            "website_payment/static/tests/builder/**/*",
        ],
        "website.website_builder_assets": [
            "website_payment/static/src/website_builder/**/*",
        ],
    },
    "auto_install": True,
}
