# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models


class PosSession(models.Model):
    _inherit = 'pos.session'

    crm_team_id = fields.Many2one('crm.team', related='config_id.crm_team_id', string="Sales Team", readonly=True)

    @api.model
    def _load_pos_data_models(self, config):
        data = super()._load_pos_data_models(config)
        data += ['sale.order', 'sale.order.line']
        return data
