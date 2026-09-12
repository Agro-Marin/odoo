{
    "name": "IoT Ingenico Terminal",
    "category": "Supply Chain/IoT",
    "summary": "Drive an Ingenico payment terminal from an IoT Box",
    "description": """
Adds the IoT Box driver for Ingenico payment terminals, which speak a socket
protocol. Install pos_iot_ingenico as well to pay with one from the Point of Sale.
""",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "iot",
    ],
    "iot_handlers_in_image": True,
    "installable": True,
}
