{
    "name": "SMS on Events",
    "version": "1.0",
    "category": "Marketing/Events",
    "description": "Schedule SMS in event management",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "event",
        "sms",
    ],
    "data": [
        "data/sms_data.xml",
        "security/ir.model.access.csv",
        "security/sms_security.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "event_sms/static/src/template_reference_field/*",
        ],
    },
    "installable": True,
    "auto_install": True,
}
