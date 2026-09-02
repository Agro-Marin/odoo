# -*- coding: utf-8 -*-
{
    "name": "Mass mailing on course members",
    "version": "1.0",
    "category": "Marketing/Email Marketing",
    "description": """
Mass mail course members
========================

Bridge module adding UX requirements to ease mass mailing of course members.
        """,
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "website_slides",
        "mass_mailing",
    ],
    "data": [
        "views/slide_channel_views.xml",
    ],
    "auto_install": True,
}
