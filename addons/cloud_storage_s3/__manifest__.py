{
    "name": "Cloud Storage S3",
    "version": "19.0.2.0.0",
    "category": "Technical Settings",
    "summary": "Store attachments in Amazon S3, with an optional local mirror",
    "author": "AgroMarin",
    "website": "https://www.agromarin.mx",
    "license": "LGPL-3",
    "depends": [
        "cloud_storage",
    ],
    "external_dependencies": {
        "python": [
            "boto3",
        ],
    },
    "data": [
        "data/ir_cron.xml",
        "views/settings.xml",
    ],
    "uninstall_hook": "uninstall_hook",
}
