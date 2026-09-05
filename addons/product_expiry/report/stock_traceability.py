from odoo import api, models
from odoo.tools import format_date

# `stock` builds every traceability row as a positional list of strings:
# [reference, product, date, lot_name, from, to, quantity]
# (stock/report/stock_traceability.py, `_final_vals_to_lines`). The expiration
# date belongs right after the lot it qualifies.
LOT_COLUMN = 3


class StockTraceabilityReport(models.TransientModel):
    _inherit = "stock.traceability.report"

    @api.model
    def _prepare_dict_move(self, level, parent_id, move_line, unfoldable=False):
        res = super()._prepare_dict_move(
            level, parent_id, move_line, unfoldable=unfoldable
        )
        res["expiration_date"] = move_line.lot_id.expiration_date
        return res

    @api.model
    def _final_vals_to_lines(self, final_vals):
        lines = super()._final_vals_to_lines(final_vals)
        for line, data in zip(lines, final_vals, strict=True):
            expiration_date = data.get("expiration_date")
            # Kept next to `lot_name` so the client can read it without
            # counting positions in `columns`.
            line["expiration_date"] = expiration_date
            line["columns"].insert(
                LOT_COLUMN + 1,
                format_date(self.env, expiration_date) if expiration_date else "",
            )
        return lines
