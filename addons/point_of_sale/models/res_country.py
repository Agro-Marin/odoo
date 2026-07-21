from odoo import api, models


class ResCountry(models.Model):
    _name = "res.country"
    _inherit = ["res.country", "pos.load.mixin"]

    @api.model
    def _load_pos_data_country_ids(self, data, config):
        """Countries reachable from the data loaded in the session.

        Shared with `res.country.state`, which scopes itself to the same countries.
        """
        country_ids = self._load_pos_data_referenced_ids(
            data, "res.partner", "country_id"
        )
        # The receipt prints the company address and its country `vat_label`, and
        # localizations dereference `company.account_fiscal_country_id.code`, so both
        # company countries are needed even when no loaded partner refers to them.
        country_ids.add(config.company_id.country_id.id)
        country_ids.add(config.company_id.account_fiscal_country_id.id)
        country_ids.discard(False)
        return country_ids

    @api.model
    def _load_pos_data_domain(self, data, config):
        # Loading every country on Earth costs more than the whole rest of the
        # payload on a small shop, for records the session never resolves.
        return [("id", "in", list(self._load_pos_data_country_ids(data, config)))]

    @api.model
    def _load_pos_data_fields(self, config):
        return ["id", "name", "code", "vat_label"]
