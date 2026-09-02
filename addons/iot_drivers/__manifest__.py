{
    "name": "Hardware Proxy",
    "category": "Hidden",
    "sequence": 6,
    "summary": "Connect the Web Client to Hardware Peripherals",
    "description": """
Hardware Poxy
=============

This module allows you to remotely use peripherals connected to this server.

This modules only contains the enabling framework. The actual devices drivers
are found in other modules that must be installed separately.

""",
    "author": "Odoo S.A.",
    "website": "https://www.odoo.com/app/iot",
    "license": "LGPL-3",
    "assets": {
        "iot_drivers.assets": [
            "iot_drivers/static/**/*",
        ],
    },
    "installable": False,
}
