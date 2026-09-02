{
    "name": "Calendar - SMS",
    "version": "1.1",
    "category": "Productivity/Calendar",
    "summary": "Send text messages as event reminders",
    "description": "Send text messages as event reminders",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "calendar",
        "sms",
    ],
    "data": [
        "data/sms_data.xml",
        "views/calendar_views.xml",
    ],
    "auto_install": True,
}
