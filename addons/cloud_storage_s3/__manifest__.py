{
    "name": "Cloud Storage S3",
    "version": "19.0.3.0.0",
    "category": "Technical Settings",
    "summary": "Store attachments in Amazon S3, with an optional local mirror",
    "author": "AgroMarin",
    "website": "https://www.agromarin.mx",
    "license": "LGPL-3",
    "depends": [
        "cloud_storage",
        "credential",
    ],
    "external_dependencies": {
        "python": [
            "boto3",
        ],
    },
    "data": [
        "data/credential_category_data.xml",
        "data/ir_cron.xml",
        "views/settings.xml",
    ],
    "uninstall_hook": "uninstall_hook",
}
