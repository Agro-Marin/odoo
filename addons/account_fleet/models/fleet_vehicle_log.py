# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class FleetVehicleLog(models.Model):
    _inherit = "fleet.vehicle.log"


    account_move_line_id = fields.Many2one(
        comodel_name="account.move.line",
    )
    account_move_state = fields.Selection(
        related="account_move_line_id.parent_state",
    )
    vehicle_id = fields.Many2one(
        compute="_compute_vehicle_id", store=True,
        readonly=False,
    )
    amount = fields.Monetary(
        compute="_compute_amount", store=True,
        inverse="_inverse_amount",
        readonly=False,
    )


    @api.ondelete(at_uninstall=False)
    def _unlink_if_no_linked_bill(self):
        if self.env.context.get("ignore_linked_bill_constraint"):
            return
        if any(log.account_move_line_id for log in self):
            raise UserError(_(
                "You cannot delete log services records because one or more of them were bill created."
            ))

    @api.depends("account_move_line_id.vehicle_id")
    def _compute_vehicle_id(self):
        for log in self:
            # We avoid emptying the vehicle_id as it is a required field
            if not log.account_move_line_id.vehicle_id:
                continue
            log.vehicle_id = log.account_move_line_id.vehicle_id

    @api.depends("account_move_line_id.price_subtotal")
    def _compute_amount(self):
        for log in self:
            log.amount = log.account_move_line_id.debit

    def _inverse_amount(self):
        if any(service.account_move_line_id for service in self):
            raise UserError(_(
                "You cannot modify amount of services linked to an account move line. "
                "Do it on the related accounting entry instead."
            ))

    def action_open_account_move(self):
        self.ensure_one()
        return {
            "name": _("Bill"),
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "view_mode": "form",
            "target": "current",
            "res_id": self.account_move_line_id.move_id.id,
        }
