{
    "name": "IoT Six Terminal",
    "category": "Administration/IoT",
    "summary": "Drive a Six payment terminal from an IoT Box",
    "description": """
Adds the IoT Box driver for Six payment terminals over the vendor TIM library,
which the box downloads on first use. Install pos_iot_six as well to pay with one
from the Point of Sale.
""",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": ["iot_payment_terminal"],
    "iot_handlers_in_image": True,
    "installable": True,
}
