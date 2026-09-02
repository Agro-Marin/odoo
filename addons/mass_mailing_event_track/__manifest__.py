# -*- coding: utf-8 -*-
{
    "name": "Mass mailing on track speakers",
    "version": "1.0",
    "category": "Marketing/Email Marketing",
    "description": """
Mass mail event track speakers
==============================

Bridge module adding UX requirements to ease mass mailing of event track speakers.
        """,
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "website_event_track",
        "mass_mailing",
    ],
    "data": [
        "views/event_views.xml",
    ],
    "auto_install": True,
}
