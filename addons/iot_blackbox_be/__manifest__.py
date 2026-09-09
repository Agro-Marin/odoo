{
    "name": "IoT Belgian Fiscal Data Module",
    "category": "Administration/IoT",
    "summary": "Talk to a Belgian fiscal data module attached to an IoT Box",
    "description": """
Adds the IoT Box driver for the Belgian fiscal data module (blackbox). The
driver only reports the device; pos_blackbox_be carries the fiscal rules.
""",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": ["iot"],
    "iot_handlers_always": True,
    "iot_handlers_in_image": True,
    "installable": True,
}
