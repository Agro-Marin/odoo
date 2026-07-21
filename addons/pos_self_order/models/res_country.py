from odoo import api, models


class ResCountry(models.Model):
    _name = 'res.country'
    _inherit = ['res.country', 'pos.load.mixin']

    @api.model
    def _load_pos_self_data_fields(self, config):
        fields = super()._load_pos_self_data_fields(config)
        return fields + ["state_ids"]

    @api.model
    def _load_pos_self_data_domain(self, data, config):
        # The kiosk asks the customer to pick a country in the address form
        # (`preset_info_popup`), so unlike the PoS itself it genuinely needs the
        # whole list -- it cannot be scoped to the countries already referenced by
        # the session's own data.
        return []
