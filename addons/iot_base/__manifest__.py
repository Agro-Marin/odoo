{
    "name": "IoT Base",
    "version": "1.0",
    "category": "Hidden",
    "description": """
Base tools required by all IoT related modules.
===============================================
""",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "web",
    ],
    "assets": {
        "web.assets_backend": [
            "iot_base/static/src/network_utils/*",
            "iot_base/static/src/device_controller.js",
        ],
    },
    "installable": True,
}
