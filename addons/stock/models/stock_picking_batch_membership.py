from odoo import models

from ..tools import debug_log as dbg


class StockPickingBatchMembership(models.Model):
    _inherit = "stock.picking"

    def update_batch_user(self, user_id):
        pickings = self.filtered(lambda p: p.user_id.id != user_id)
        dbg.lifecycle.debug(
            "update_batch_user: %s -> user %s", dbg.rec(pickings), user_id
        )
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

    def _get_pickings_detached_from_batch(self):
        return self.browse(self.env.context.get("pickings_to_detach"))

    def _detach_from_batches_after_validation(self):
        if not any(picking.state == "done" for picking in self):
            return self.browse()
        to_rebatch = self.browse()
        detached = self._get_pickings_detached_from_batch()
        if self and detached:
            detached.batch_id = False
            detached.move_ids.filtered(lambda m: not m.quantity).picked = False
            to_rebatch |= detached
        for picking in self.filtered(lambda p: p.state == "done"):
            if picking.batch_id and any(
                p.state != "done" for p in picking.batch_id.picking_ids
            ):
                picking.batch_id = False
            to_rebatch |= picking.backorder_ids
        dbg.pipeline.debug(
            "_detach_from_batches_after_validation: detached %s, to rebatch %s",
            dbg.rec(detached),
            dbg.rec(to_rebatch),
        )
        return to_rebatch

    def _rebatch_after_validation(self):
        return None

    def _detach_from_batch_before_backorder(self):
        detached = self._get_pickings_detached_from_batch()
        leaving = self.filtered(
            lambda picking: (
                picking.batch_id
                and picking.state != "done"
                and any(p not in self for p in picking.batch_id.picking_ids - detached)
            )
        )
        if leaving:
            dbg.pipeline.debug(
                "_detach_from_batch_before_backorder: %s leave their batch",
                dbg.rec(leaving),
            )
            leaving.batch_id = False
