{
    "name": "Skills Events",
    "version": "1.0",
    "category": "Hidden",
    "summary": "Link training events to resume of your employees",
    "description": """
Events and Skills for HR
============================

This module add completed course events to resume for employees.
        """,
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "hr_skills",
        "event",
    ],
    "data": [
        "views/hr_resume_line_views.xml",
        "views/event_event_views.xml",
        "views/hr_views.xml",
    ],
    "assets": {},
    "auto_install": True,
}
