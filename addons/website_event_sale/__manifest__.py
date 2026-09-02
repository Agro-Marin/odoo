{
    "name": "Online Event Ticketing",
    "category": "Website/Website",
    "summary": "Sell event tickets online",
    "description": """
Sell event tickets through eCommerce app.
    """,
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "website_event",
        "event_sale",
        "website_sale",
    ],
    "data": [
        "report/event_sale_report_views.xml",
        "views/event_event_views.xml",
        "views/website_event_templates.xml",
        "views/website_sale_templates.xml",
    ],
    "assets": {
        "web.assets_tests": [
            "website_event_sale/static/tests/**/*",
        ],
        "web.assets_frontend": [
            "website_event_sale/static/src/scss/*.scss",
        ],
    },
    "auto_install": True,
}
