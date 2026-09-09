{
    "name": "IoT Payment Terminal",
    "category": "Supply Chain/IoT",
    "summary": "Shared ctypes scaffolding for payment terminals driven over a vendor library",
    "description": """
Base driver for payment terminals whose vendor ships a C library rather than a
protocol. Install a terminal module such as iot_six or iot_worldline; this one
carries only what those have in common.
""",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": ["iot"],
    "iot_handlers_in_image": True,
    "installable": True,
}
