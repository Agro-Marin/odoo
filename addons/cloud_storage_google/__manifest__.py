{
    "name": "Cloud Storage Google",
    "version": "1.0",
    "category": "Technical Settings",
    "summary": "Store chatter attachments in the Google cloud",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "cloud_storage",
    ],
    "external_dependencies": {
        "python": [
            "google-auth",
        ],
        "apt": {
            "google-auth": "python3-google-auth",
        },
    },
    "data": [
        "views/settings.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "cloud_storage_google/static/src/**/*",
        ],
    },
    "uninstall_hook": "uninstall_hook",
}
