# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import Command, models, fields


class FleetVehicle(models.Model):
    _inherit = 'fleet.vehicle'


    account_move_ids = fields.One2many(
        comodel_name='account.move',
        compute='_compute_move_ids',
    )
    bill_count = fields.Integer(
        string="Bills Count",
        compute='_compute_move_ids',
    )


    def _compute_move_ids(self):
        if not self.env.user.has_group('account.group_account_readonly'):
            self.account_move_ids = False
            self.bill_count = 0
            return

        moves = self.env['account.move.line']._read_group(
            domain=[
                ('vehicle_id', 'in', self.ids),
                ('parent_state', '!=', 'cancel'),
                ('move_id.move_type', 'in', self.env['account.move'].get_purchase_types())
            ],
            groupby=['vehicle_id'],
            aggregates=['move_id:array_agg'],
        )
        vehicle_move_mapping = {vehicle.id: set(move_ids) for vehicle, move_ids in moves}
        for vehicle in self:
            vehicle.account_move_ids = [Command.set(vehicle_move_mapping.get(vehicle.id, []))]
            vehicle.bill_count = len(vehicle.account_move_ids)

    def action_view_bills(self):
        self.ensure_one()
        form_view_ref = self.env.ref('account.view_move_form', False)
        list_view_ref = self.env.ref('account_fleet.account_move_view_tree', False)
        action = self.env['ir.actions.act_window']._for_xml_id('account.action_move_in_invoice_type')
        action.update({
            'views': [(list_view_ref.id, 'list'), (form_view_ref.id, 'form')],
            'domain': [('id', 'in', self.account_move_ids.ids)],
        })
        return action
