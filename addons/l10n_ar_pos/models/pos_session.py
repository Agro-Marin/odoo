# -*- coding: utf-8 -*-
from odoo import models, api


class PosSession(models.Model):
    _inherit = 'pos.session'

    @api.model
    def _get_model_names_to_load(self, config):
        data = super()._get_model_names_to_load(config)
        if self.env.company.country_id.code == 'AR':
            data += ['l10n_ar.afip.responsibility.type', 'l10n_latam.identification.type']
        return data
