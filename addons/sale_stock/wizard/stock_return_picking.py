from odoo import models


class StockReturnPicking(models.TransientModel):
    _inherit = "stock.return.picking"

    # No `_prepare_move_default_values` / `_prepare_picking_default_values_based_on`
    # override is needed here (upstream shipped both in a never-imported file):
    # the return move inherits `sale_line_id` through `move_id.copy()` (the field
    # is copyable), and the return picking's `sale_id` is a stored compute that
    # derives from its moves' `sale_line_id` and the propagated `reference_ids` —
    # setting it in the copy vals would only fire the reference-linking inverse
    # on a picking that has no moves yet.

    def _get_proc_values(self, line):
        sol = line.move_id.sale_line_id
        if sol:
            return sol._prepare_procurement_vals()
        return super()._get_proc_values(line)
