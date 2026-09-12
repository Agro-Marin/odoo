{
    "name": "IoT Belgian Fiscal Data Module",
    "category": "Supply Chain/IoT",
    "summary": "Talk to a Belgian fiscal data module attached to an IoT Box",
    "description": """
Adds the IoT Box driver for the Belgian fiscal data module (blackbox). The
driver only reports the device; pos_blackbox_be carries the fiscal rules.
""",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "iot",
    ],
    "assets": {
        "iot_blackbox_be.assets_messages": [
            "iot_blackbox_be/static/src/fdm_messages.js",
        ],
        "web.assets_backend": [
            (
                "include",
                "iot_blackbox_be.assets_messages",
            ),
        ],
        "web.assets_unit_tests": [
            "iot_blackbox_be/static/tests/**/*",
        ],
    },
    "iot_handlers_in_image": True,
    "installable": True,
    "auto_install": True,
}
