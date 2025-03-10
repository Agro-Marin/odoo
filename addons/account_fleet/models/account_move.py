# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import models, _


class AccountMove(models.Model):
    _inherit = 'account.move'


    def _post(self, soft=True):
        # We need the move name to be set, but we also need to know which move are posted for the first time.
        posted = super()._post(soft)
        val_list = []
        log_list = []
        for line in posted.line_ids:
            if (
                line.move_id.move_type != 'in_invoice'
                or line.display_type != 'product'
                or not line.product_id
                or not line.vehicle_id
                or line.vehicle_log_ids
            ):
                continue
            val = line._prepare_vehicle_log()
            log = _('Service Vendor Bill: %s', line.move_id._get_html_link())
            val_list.append(val)
            log_list.append(log)
        log_ids = self.env['fleet.vehicle.log'].create(val_list)
        for log_service_id, log in zip(log_ids, log_list):
            log_service_id.message_post(body=log)
        return posted

    def button_draft(self):
        res = super().button_draft()
        for move in self:
            move.line_ids.filtered(
                lambda l: l.vehicle_id
            ).sudo().vehicle_log_ids.with_context(
                ignore_linked_bill_constraint=True
            ).unlink()
        return res
