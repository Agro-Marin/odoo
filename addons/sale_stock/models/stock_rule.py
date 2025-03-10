from odoo import models


class StockRule(models.Model):
    "Inherit StockRule"

    _inherit = "stock.rule"

    def _get_custom_move_fields(self):
        fields = super(StockRule, self)._get_custom_move_fields()
        fields += ["sale_line_id", "partner_id", "sequence", "to_refund"]
        return fields
