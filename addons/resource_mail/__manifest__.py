{
    "name": "Resource Mail",
    "version": "1.0",
    "category": "Hidden",
    "description": "Integrate features developed in Mail in use case involving resources instead of users",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "resource",
        "mail",
    ],
    "assets": {
        "web.assets_backend": [
            "resource_mail/static/src/**/*",
        ],
        "web.assets_unit_tests": [
            "resource_mail/static/tests/**/*",
        ],
    },
    "auto_install": True,
}
