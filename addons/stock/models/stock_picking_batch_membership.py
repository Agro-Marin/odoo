from odoo import models
from odoo.libs.debug_log import DebugLog

from .stock_picking import DONE_CANCEL_STATES

_debug = DebugLog(__name__)


class StockPickingBatchMembership(models.Model):
    _inherit = "stock.picking"

    def update_batch_user(self, user_id):
        pickings = self.filtered(lambda p: p.user_id.id != user_id)
        _debug.lifecycle("batch_user_updated", pickings=pickings, user=user_id)
        pickings.write({"user_id": user_id})
        for pick in pickings:
            if user_id:
                log_message = self.env._(
                    "Assigned to %s Responsible", pick.batch_id._get_html_link()
                )
            else:
                log_message = self.env._(
                    "Unassigned responsible from %s", pick.batch_id._get_html_link()
                )
            pick.message_post(body=log_message)

    def _get_pickings_detached_from_batch(self, batch):
        if not batch:
            return self.browse()
        return (
            batch.picking_ids.filtered(
                lambda picking: picking.state not in DONE_CANCEL_STATES
            )
            - self
        )

    def _detach_unvalidated_from_batch(self, batch):
        detached = self._get_pickings_detached_from_batch(batch)
        if detached:
            _debug.pipeline("detach_unvalidated", pickings=detached, batch=batch)
            detached.batch_id = False
            detached.move_ids.filtered(lambda m: not m.quantity).picked = False
        return detached

    def _detach_from_batches_after_validation(self):
        to_rebatch = self.browse()
        for picking in self.filtered(lambda p: p.state == "done"):
            if picking.batch_id and any(
                p.state != "done" for p in picking.batch_id.picking_ids
            ):
                picking.batch_id = False
            to_rebatch |= picking.backorder_ids
        _debug.pipeline("rebatch", pickings=to_rebatch)
        return to_rebatch

    def _rebatch_after_validation(self, excluded_batches=None):
        return None

    def _detach_from_batch_before_backorder(self):
        leaving = self.filtered(
            lambda picking: (
                picking.batch_id
                and picking.state != "done"
                and any(p not in self for p in picking.batch_id.picking_ids)
            )
        )
        if leaving:
            _debug.pipeline("detach_before_backorder", pickings=leaving)
            leaving.batch_id = False
