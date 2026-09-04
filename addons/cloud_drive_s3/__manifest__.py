{
    "name": "Cloud Drive (S3)",
    "version": "19.0.2.0.0",
    "category": "Productivity/Documents",
    "summary": "S3 drive with browser-direct upload, preview and delete, and per-user folder sharing",
    "author": "AgroMarin",
    "license": "LGPL-3",
    "depends": [
        "web",
        "credential",
    ],
    "external_dependencies": {
        "python": [
            "boto3",
        ],
    },
    "data": [
        "security/res_groups_security.xml",
        "security/ir.model.access.csv",
        "data/credential_category_data.xml",
        "views/cloud_drive_config_views.xml",
        "views/drive_action.xml",
        "views/cloud_drive_access_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "cloud_drive_s3/static/src/**/*",
            (
                "remove",
                "cloud_drive_s3/static/src/**/*.dark.scss",
            ),
        ],
        "web.assets_web_dark": [
            "cloud_drive_s3/static/src/drive/drive_action.dark.scss",
        ],
    },
    "application": True,
}
