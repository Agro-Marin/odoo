{
    "name": "IoT Worldline Terminal",
    "category": "Supply Chain/IoT",
    "summary": "Drive a Worldline payment terminal from an IoT Box",
    "description": """
Adds the IoT Box driver for Worldline payment terminals over the vendor CTEP
library, which the box downloads on first use. Install pos_iot_worldline as well
to pay with one from the Point of Sale.
""",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "iot_payment_terminal",
    ],
    "iot_handlers_in_image": True,
}
