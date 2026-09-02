# -*- coding: utf-8 -*-

{
    "name": "Maintenance",
    "version": "1.0",
    "category": "Supply Chain/Maintenance",
    "sequence": 100,
    "summary": "Track equipment and manage maintenance requests",
    "description": """
Track equipment and maintenance requests""",
    "author": "Odoo S.A.",
    "website": "https://www.odoo.com/app/maintenance",
    "license": "LGPL-3",
    "depends": [
        "mixin_recurrence",
        "mail",
    ],
    "data": [
        "security/maintenance.xml",
        "security/ir.model.access.csv",
        "data/maintenance_data.xml",
        "data/mail_activity_type_data.xml",
        "data/mail_message_subtype_data.xml",
        "views/maintenance_views.xml",
        "views/mail_activity_views.xml",
        "views/res_config_settings_views.xml",
    ],
    "demo": [
        "data/maintenance_demo.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "maintenance/static/src/**/*",
        ],
        "web.assets_tests": [
            "maintenance/static/tests/tours/**/*",
        ],
    },
    "installable": True,
    "application": True,
}
