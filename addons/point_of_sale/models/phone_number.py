from odoo import api, models


class PhoneNumber(models.Model):
    _name = "phone.number"
    _inherit = ["phone.number", "mixin.pos.load"]

    @api.model
    def _load_pos_data_domain(self, data, config):
        ids = set()
        for model in ("res.company", "res.partner", "res.users"):
            for record in data.get(model, []):
                ids.update(record.get("phone_ids") or [])
        return [("id", "in", list(ids))]

    @api.model
    def _load_pos_data_fields(self, config):
        return ["id", "number", "type", "sanitized", "primary", "sequence", "label"]
