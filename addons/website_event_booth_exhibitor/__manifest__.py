{
    "name": "Booths/Exhibitors Bridge",
    "version": "1.1",
    "category": "Marketing/Events",
    "summary": "Event Booths, automatically create a sponsor.",
    "description": """
Automatically create a sponsor when renting a booth.
    """,
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "website_event_exhibitor",
        "website_event_booth",
    ],
    "data": [
        "data/event_booth_category_data.xml",
        "views/event_booth_category_views.xml",
        "views/event_booth_views.xml",
        "views/event_booth_registration_templates.xml",
        "views/event_booth_templates.xml",
        "views/mail_templates.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "/website_event_booth_exhibitor/static/src/interactions/booth_sponsor_details.js",
        ],
        "web.assets_tests": [
            "website_event_booth_exhibitor/static/tests/tours/website_event_booth_exhibitor_steps.js",
            "website_event_booth_exhibitor/static/tests/tours/website_event_booth_exhibitor.js",
        ],
    },
    "auto_install": True,
}
