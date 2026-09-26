from odoo import models
from odoo.exceptions import UserError
from odoo.fields import Domain

from .stock_picking import TRIP_MODES


class StockPickingBatch(models.Model):
    _inherit = "stock.picking.batch"

    def action_load_operator_sales(self):
        """Board the ready deliveries of the orders the trip's operator sold.

        A salesperson who delivers takes his own customers' goods: his trip is
        built from his portfolio, whichever customers he ends up visiting.
        """
        self.check_singleton()
        if self.date_departure:
            raise UserError(
                self.env._(
                    "Trip %s has departed: it takes no more transfers.", self.name
                )
            )
        salesperson = self.operator_id.user_id
        if not salesperson:
            raise UserError(
                self.env._(
                    "Choose an operator with a user: his sales are found through it."
                )
            )
        domain = Domain(
            [
                ("batch_id", "=", False),
                ("state", "=", "assigned"),
                ("picking_type_code", "=", "outgoing"),
                ("sale_id.user_id", "=", salesperson.id),
                ("company_id", "=", self.company_id.id),
            ]
        )
        if self.picking_type_id:
            domain &= Domain("picking_type_id", "=", self.picking_type_id.id)
        # Only what leaves whole: a partly reserved transfer would be handed over
        # short and leave a backorder behind the salesperson's back.
        pickings = (
            self.env["stock.picking"]
            .search(domain)
            .filtered(
                lambda picking: (
                    picking._get_dispatch_mode() in TRIP_MODES
                    and all(
                        move.state == "assigned"
                        for move in picking.move_ids
                        if move.state not in ("done", "cancel")
                    )
                )
            )
        )
        if not pickings:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "message": self.env._(
                        "No delivery of %(salesperson)s's sales is ready to leave.",
                        salesperson=salesperson.name,
                    ),
                    "type": "warning",
                },
            }
        pickings.batch_id = self
        return True
