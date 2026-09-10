from odoo import api, fields, models
from odoo.fields import Domain


class EfakturProductCode(models.Model):
    _name = "l10n_id_efaktur_coretax.product.code"
    _description = "Product categorization according to E-Faktur"
    _rec_name = "code"

    code = fields.Char()
    description = fields.Text()

    @api.depends("code", "description")
    def _compute_display_name(self):
        for record in self:
            record.display_name = f"{record.code} - {record.description}"

    def _search_display_name(self, operator, value):
        if (
            operator in ("ilike", "=ilike", "like", "=like")
            and value
            and isinstance(value, str)
        ):
            code, separator, description = value.partition(" - ")
            if separator:
                return Domain("code", operator, code) & Domain(
                    "description", operator, description
                )
            return Domain("code", operator, value) | Domain(
                "description", operator, value
            )
        return super()._search_display_name(operator, value)
