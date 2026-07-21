from odoo import api, models


class ResCountryState(models.Model):
    _name = "res.country.state"
    _inherit = ["res.country.state", "pos.load.mixin"]

    @api.model
    def _load_pos_data_domain(self, data, config):
        # ~1900 states world-wide, none of which the session resolves beyond the
        # handful its partners and its own company point at. Scoping by country
        # rather than by referenced state keeps `country_id.state_ids` meaningful
        # for the loaded countries (pos_self_order builds its address dropdowns
        # from it) while dropping the rest of the table.
        country_ids = self.env["res.country"]._load_pos_data_country_ids(data, config)
        state_ids = self._load_pos_data_referenced_ids(data, "res.partner", "state_id")
        # A partner may carry a state whose country is not itself loaded.
        state_ids.add(config.company_id.state_id.id)
        state_ids.discard(False)
        return [
            "|",
            ("country_id", "in", list(country_ids)),
            ("id", "in", list(state_ids)),
        ]

    @api.model
    def _load_pos_data_fields(self, config):
        return ["id", "name", "code", "country_id"]
