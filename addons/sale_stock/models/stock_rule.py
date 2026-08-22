from odoo import models


class StockRule(models.Model):
    _inherit = "stock.rule"

    # ------------------------------------------------------------
    # HELPER METHODS
    # ------------------------------------------------------------

    def _get_fields_custom_move(self):
        fields = super()._get_fields_custom_move()
        fields += ["sale_line_id", "partner_id", "sequence", "to_refund"]
        return fields
