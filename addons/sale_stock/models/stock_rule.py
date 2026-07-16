from odoo import models


class StockRule(models.Model):
    _inherit = "stock.rule"

    # ------------------------------------------------------------
    # HELPER METHODS
    # ------------------------------------------------------------

    def _get_custom_move_fields(self):
        fields = super()._get_custom_move_fields()
        fields += ["sale_line_id", "partner_id", "sequence", "to_refund"]
        return fields
