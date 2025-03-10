from odoo import fields, models


class ProcurementGroup(models.Model):
    "Inherit ProcurementGroup"

    _inherit = "procurement.group"

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    sale_id = fields.Many2one(
        "sale.order",
        "Sale Order",
    )
