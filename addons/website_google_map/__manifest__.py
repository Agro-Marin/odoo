{
    "name": "Google Maps",
    "version": "1.0",
    "category": "Website/Website",
    "summary": "Show your company address on Google Maps",
    "description": """
Show your company address/partner address on Google Maps. Configure an API key in the Website settings.
    """,
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "geocoding",
        "website_partner",
    ],
    "data": [
        "views/google_map_templates.xml",
    ],
    "installable": True,
}
