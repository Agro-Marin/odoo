from odoo import fields, models


class ResCompany(models.Model):
    """Inherit ResCompany"""

    _inherit = "res.company"

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    po_lock = fields.Selection(
        selection=[
            ("edit", "Allow to edit purchase orders"),
            ("lock", "Confirmed purchase orders are not editable"),
        ],
        string="Purchase Order Modification",
        default="edit",
        help="Purchase Order Modification used when you want to purchase order editable after confirm",
    )
    po_lead = fields.Float(
        string="Purchase Lead Time",
        default=0.0,
        required=True,
        help="Margin of error for vendor lead times. When the system "
        "generates Purchase Orders for procuring products, "
        "they will be scheduled that many days earlier "
        "to cope with unexpected vendor delays.",
    )
    po_approval = fields.Boolean(
        string="Require approvoal to confirm",
        help="Create an approval before confirming a RFQ.",
    )
