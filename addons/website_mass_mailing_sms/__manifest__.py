{
    "name": "Newsletter Subscribe SMS Template",
    "version": "1.0",
    "category": "Website/Website",
    "summary": "Attract visitors to subscribe to mailing lists",
    "description": """
This module adds a new template to the Newsletter Block to allow
your visitors to subscribe with their phone number.
    """,
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "website_mass_mailing",
        "mass_mailing_sms",
    ],
    "data": [
        "views/snippets/snippets_templates.xml",
        "data/ir_model_data.xml",
    ],
    "assets": {
        "website.website_builder_assets": [
            "website_mass_mailing_sms/static/src/website_builder/**/*",
        ],
    },
    "auto_install": True,
}
