from odoo import fields, models


class PurchaseMassCancelOrders(models.TransientModel):
    _name = "purchase.mass.cancel.orders"
    _inherit = "order.mass.cancel.mixin"
    _description = "Cancel multiple RFQs/purchase orders"

    order_ids = fields.Many2many(
        comodel_name="purchase.order",
        relation="purchase_order_mass_cancel_wizard_rel",
        string="Purchase orders to cancel",
        default=lambda self: self.env.context.get("active_ids"),
    )
