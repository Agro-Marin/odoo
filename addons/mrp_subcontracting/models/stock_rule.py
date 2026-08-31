from odoo import models


class StockRule(models.Model):
    _inherit = "stock.rule"

    def _push_prepare_move_copy_values(self, move_to_copy, new_date):
        new_move_vals = super()._push_prepare_move_copy_values(move_to_copy, new_date)
        new_move_vals["is_subcontract"] = False
        return new_move_vals

    def _prepare_stock_move_vals(self, procurement):
        move_values = super()._prepare_stock_move_vals(procurement)
        dest_moves = procurement.values.get("move_dest_ids")
        if not move_values.get("partner_id") and dest_moves:
            subcontractor = dest_moves.raw_material_production_id.subcontractor_id
            if subcontractor:
                move_values["partner_id"] = subcontractor.id
        return move_values
