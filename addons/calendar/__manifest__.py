{
    "name": "Calendar",
    "version": "1.1",
    "category": "Productivity/Calendar",
    "sequence": 165,
    "summary": "Schedule employees' meetings",
    "description": """
This is a full-featured calendar system.
========================================

It supports:
------------
    - Calendar of events
    - Recurring events

If you need to manage your meetings, you should install the CRM module.
    """,
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "mail",
        "resource",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/calendar_security.xml",
        "data/calendar_cron.xml",
        "data/mail_template_data.xml",
        "data/calendar_data.xml",
        "data/mail_activity_type_data.xml",
        "data/mail_message_subtype_data.xml",
        "views/mail_activity_views.xml",
        "views/calendar_templates.xml",
        "views/calendar_views.xml",
        "views/res_config_settings_views.xml",
        "views/res_partner_views.xml",
        "views/res_users_views.xml",
        "wizard/calendar_provider_config.xml",
        "wizard/calendar_popover_delete_wizard.xml",
        "wizard/mail_activity_schedule_views.xml",
    ],
    "demo": [
        "data/calendar_demo.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "calendar/static/src/**/*",
        ],
        "web.assets_unit_tests": [
            "calendar/static/tests/**/*.js",
            (
                "remove",
                "calendar/static/tests/tours/**/*",
            ),
        ],
        "web.assets_tests": [
            "calendar/static/tests/tours/**/*",
        ],
    },
    "installable": True,
    "application": True,
}
