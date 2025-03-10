from odoo import fields, models


class PaymentProvider(models.Model):
    """Extends the 'payment.provider' model to add sales order reference configuration.

    This module introduces a selection field to define the communication type (e.g., based on document ref or partner)
    that will appear on sales orders. This helps customize the payment communication displayed to customers.
    """

    _inherit = "payment.provider"

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    # Selection
    so_reference_type = fields.Selection(
        selection=[
            ("so_name", "Based on Document Reference"),
            ("partner", "Based on Customer ID"),
        ],
        string="Communication",
        default="so_name",
        help="You can set here the communication type that will appear on sales orders."
        "The communication will be given to the customer when they choose the payment method.",
    )
