# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # Multi-membership is a sales_team behaviour: the parameter, the reader
    # (crm.team._is_membership_multi), every code path that branches on it and
    # the "Activate Multi-team" banner all live here. The field was declared in
    # crm instead, so a database with sale but without crm could switch it on
    # from the banner and had nowhere to switch it back off.
    is_membership_multi = fields.Boolean(
        string='Multi Teams', config_parameter='sales_team.membership_multi')
