from odoo import models, api


class L10n_ArAfipResponsibilityType(models.Model):
    _name = 'l10n_ar.afip.responsibility.type'
    _inherit = ['l10n_ar.afip.responsibility.type', 'mixin.pos.load']

    @api.model
    def _load_pos_data_fields(self, config):
        return ['name']
