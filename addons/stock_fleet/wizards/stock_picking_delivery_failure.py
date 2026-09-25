from odoo import fields, models


class StockPickingDeliveryFailure(models.TransientModel):
    """Reason given by the driver when a stop could not be delivered."""

    _name = "stock.picking.delivery.failure"
    _description = "Undelivered Transfer"

    picking_id = fields.Many2one(
        comodel_name="stock.picking",
        required=True,
        ondelete="cascade",
    )
    reason = fields.Text(required=True)

    def action_confirm(self):
        self.check_singleton()
        self.picking_id._register_delivery_failure(self.reason)
        return {"type": "ir.actions.act_window_close"}
