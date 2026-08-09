from odoo import fields, models


class SaleMassCancelOrders(models.TransientModel):
    _name = "sale.mass.cancel.orders"
    _inherit = "order.mass.cancel.mixin"
    _description = "Cancel multiple quotations"

    order_ids = fields.Many2many(
        comodel_name="sale.order",
        relation="sale_order_mass_cancel_wizard_rel",
        string="Sale orders to cancel",
        default=lambda self: self.env.context.get("active_ids"),
    )
