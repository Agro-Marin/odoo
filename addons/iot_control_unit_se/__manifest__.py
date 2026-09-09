{
    "name": "IoT Swedish Control Unit",
    "category": "Administration/IoT",
    "summary": "Talk to a Swedish fiscal control unit attached to an IoT Box",
    "description": """
Adds the IoT Box driver for the Swedish fiscal control unit. The driver only
reports the device; l10n_se_pos carries the fiscal rules.
""",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": ["iot"],
    "iot_handlers_in_image": True,
    "installable": True,
}
