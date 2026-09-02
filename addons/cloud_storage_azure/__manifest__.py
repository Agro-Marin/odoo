{
    "name": "Cloud Storage Azure",
    "version": "1.0",
    "category": "Technical Settings",
    "summary": "Store chatter attachments in the Azure cloud",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "cloud_storage",
    ],
    "data": [
        "views/settings.xml",
    ],
    "uninstall_hook": "uninstall_hook",
}
