from odoo import api, models
from odoo.exceptions import AccessError
from odoo.fields import Domain


class MixinPosLoad(models.AbstractModel):
    _name = "mixin.pos.load"
    _description = "PoS data loading mixin"

    @api.model
    def _load_pos_data_search_read(self, data, config):
        if not config:
            raise ValueError("config must be provided to search for PoS data.")

        domain = self._server_date_to_domain(self._load_pos_data_domain(data, config))
        if domain is False:
            return []

        records = self.search(domain)
        return self._load_pos_data_read(records, config)

    @api.model
    def _load_pos_data_domain(self, data, config):
        return []

    @api.model
    def _load_pos_data_referenced_ids(self, data, model, field):
        return {record[field] for record in data.get(model, []) if record.get(field)}

    @api.model
    def _server_date_to_domain(self, domain):
        if domain is False:
            return domain

        last_server_date = self.env.context.get("pos_last_server_date", False)
        limited_loading = self.env.context.get("pos_limited_loading", True)
        model_included = self._name not in ["pos.session", "pos.config"]

        if limited_loading and last_server_date and model_included:
            domain = Domain.AND([domain, [("write_date", ">", last_server_date)]])

        return domain

    @api.model
    def _load_pos_data_read(self, records, config):
        if not config:
            raise ValueError("config must be provided to read PoS data.")

        fields = self._load_pos_data_fields(config)
        records = records._filtered_access("read").read(fields, load=False)
        return records or []

    def _unrelevant_records(self, config):
        if "active" not in self._fields:
            return []
        try:
            return (self - self.filtered("active")).ids
        except AccessError:
            return self.ids

    @api.model
    def _load_pos_data_fields(self, config):
        return []
