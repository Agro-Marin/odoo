from odoo import api, models


class IrQwebFieldMonetaryOpt(models.AbstractModel):
    _name = "ir.qweb.field.monetary_opt"
    _inherit = "ir.qweb.field.monetary"
    _description = "QWeb Field Monetary (blank when unset)"

    @api.model
    def value_to_html(self, value, options):
        if value is None or value is False:
            return ""
        return super().value_to_html(value, options)
