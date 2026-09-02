{
    "name": "Display Working Hours in Calendar",
    "version": "1.0",
    "category": "Human Resources/Employees",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "hr",
        "calendar",
    ],
    "data": [
        "views/calendar_views_calendarApp.xml",
        "views/res_partner_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "hr_calendar/static/src/**/*",
        ],
    },
    "auto_install": True,
}
