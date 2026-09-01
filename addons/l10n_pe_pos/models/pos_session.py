from odoo import models, api


class PosSession(models.Model):
    _inherit = "pos.session"

    @api.model
    def _get_model_names_to_load(self, config):
        data = super()._get_model_names_to_load(config)
        if self.env.company.country_id.code == "PE":
            data += ['l10n_pe.res.city.district', 'l10n_latam.identification.type', 'res.city']
        return data
