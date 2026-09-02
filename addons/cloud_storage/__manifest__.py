{
    "name": "Cloud Storage",
    "version": "1.0",
    "category": "Technical Settings",
    "summary": "Store chatter attachments in the cloud",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "mail",
    ],
    "data": [
        "views/settings.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "cloud_storage/static/src/core/common/**/*",
            "cloud_storage/static/src/**/web_portal/**/*",
        ],
        "mail.assets_public": [
            "cloud_storage/static/src/core/common/**/*",
        ],
    },
}
