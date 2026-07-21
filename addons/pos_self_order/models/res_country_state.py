from odoo import api, models


class ResCountryState(models.Model):
    _name = 'res.country.state'
    _inherit = ['res.country.state', 'pos.load.mixin']

    @api.model
    def _load_pos_self_data_domain(self, data, config):
        # Counterpart of the `res.country` override: the kiosk address form
        # narrows its state dropdown from the country the customer picked, so the
        # states of every selectable country have to be available.
        return []
