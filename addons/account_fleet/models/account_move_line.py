# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'


    vehicle_id = fields.Many2one(
        comodel_name='fleet.vehicle',
        string='Vehicle',
        index='btree_not_null',
    )
    need_vehicle = fields.Boolean(
        compute='_compute_need_vehicle',
        help='Used to decide whether the vehicle_id field is editable',
    )
    vehicle_log_ids = fields.One2many(
        comodel_name='fleet.vehicle.log',
        inverse_name='account_move_line_id',
        export_string_translation=False,
    )


    def write(self, vals):
        if 'vehicle_id' in vals and not vals['vehicle_id']:
            self.sudo().vehicle_log_ids.with_context(ignore_linked_bill_constraint=True).unlink()
        return super().write(vals)

    def unlink(self):
        self.sudo().vehicle_log_ids.with_context(ignore_linked_bill_constraint=True).unlink()
        return super().unlink()

    def _compute_need_vehicle(self):
        self.need_vehicle = False

    def _prepare_vehicle_log(self):
        return {
            'vehicle_id': self.vehicle_id.id,
            'vendor_id': self.partner_id.id,
            'product_id': self.product_id.id,
            'account_move_line_id': self.id,
        }
