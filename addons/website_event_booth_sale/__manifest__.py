{
    "name": "Online Event Booth Sale",
    "version": "1.0",
    "category": "Marketing/Events",
    "summary": "Events, sell your booths online",
    "description": """
Use the e-commerce to sell your event booths.
    """,
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "event_booth_sale",
        "website_event_booth",
        "website_sale",
    ],
    "data": [
        "views/event_booth_registration_templates.xml",
        "views/event_booth_templates.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "/website_event_booth_sale/static/src/interactions/*",
        ],
        "web.assets_tests": [
            "/website_event_booth_sale/static/tests/tours/**/*.js",
        ],
    },
    "auto_install": True,
}
