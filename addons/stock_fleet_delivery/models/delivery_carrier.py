from odoo import fields, models

DISPATCH_MODES = [
    ("own_fleet", "Own Fleet"),
    ("salesperson", "Salesperson Delivery"),
    ("third_party", "Third-Party Carrier"),
    ("pickup", "Customer Pickup"),
]


class DeliveryCarrier(models.Model):
    _inherit = "delivery.carrier"

    dispatch_mode = fields.Selection(
        selection=DISPATCH_MODES,
        help="How goods with this carrier leave. Own fleet and salesperson "
        "deliveries travel in a departed trip; a third-party carrier needs its "
        "tracking reference; a customer pickup needs neither. Empty counts as own fleet.",
    )
