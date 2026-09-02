# -*- coding: utf-8 -*-
{
    "name": "Mass mailing on attendees",
    "version": "1.0",
    "category": "Marketing/Email Marketing",
    "description": """
Mass mail event attendees
=========================

Bridge module adding UX requirements to ease mass mailing of event attendees.
        """,
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "event",
        "mass_mailing",
    ],
    "data": [
        "views/event_views.xml",
    ],
    "auto_install": True,
}
