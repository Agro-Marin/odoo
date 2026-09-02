{
    "name": "Live Event Tracks",
    "version": "1.0",
    "category": "Marketing/Events",
    "sequence": 1006,
    "summary": "Support live tracks: streaming, participation, youtube",
    "author": "Odoo S.A.",
    "website": "https://www.odoo.com/app/events",
    "license": "LGPL-3",
    "depends": [
        "website_event_track",
    ],
    "data": [
        "views/event_track_templates_list.xml",
        "views/event_track_templates_page.xml",
        "views/event_track_views.xml",
    ],
    "demo": [
        "data/event_track_demo.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "website_event_track_live/static/src/scss/website_event_track_live.scss",
            "website_event_track_live/static/src/interactions/*.js",
            "website_event_track_live/static/src/xml/**/*",
        ],
    },
    "installable": True,
}
