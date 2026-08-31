from odoo import api, models


class StockMoveLine(models.Model):
    _inherit = "stock.move.line"

    @api.model_create_multi
    def create(self, vals_list):
        mls = super().create(vals_list)
        mls._update_stock_move_value()
        return mls

    def write(self, vals):
        analytic_move_to_recompute = set()
        if "quantity" in vals or "move_id" in vals:
            for move_line in self:
                move_id = vals.get("move_id", move_line.move_id.id)
                analytic_move_to_recompute.add(move_id)
        valuation_fields = [
            "quantity",
            "location_id",
            "location_dest_id",
            "owner_id",
            "picked",
            "quant_id",
            "lot_id",
        ]
        valuation_trigger = any(field in vals for field in valuation_fields)
        qty_by_ml = {}
        if valuation_trigger:
            qty_by_ml = {
                ml: ml.quantity_product_uom
                for ml in self
                if ml.move_id.is_in or ml.move_id.is_out
            }
        res = super().write(vals)
        survivors = self.exists()
        if valuation_trigger:
            survivors._update_stock_move_value(qty_by_ml)
        if analytic_move_to_recompute:
            self.env["stock.move"].browse(
                analytic_move_to_recompute
            ).sudo()._create_analytic_move()
        return res

    def unlink(self):
        analytic_move_to_recompute = self.move_id
        res = super().unlink()
        analytic_move_to_recompute.sudo()._create_analytic_move()
        return res

    def _should_exclude_for_valuation(self):
        self.check_singleton()
        return bool(self.owner_id and self.owner_id != self.company_id.partner_id)

    def _update_stock_move_value(self, old_qty_by_ml=None):
        move_to_update = set()
        if not old_qty_by_ml:
            old_qty_by_ml = {}

        done_moves = self.move_id.filtered(lambda move: move.state == "done")
        classification_before = {
            move.id: (move.is_in, move.is_out) for move in done_moves
        }
        done_moves._recompute_valuation_flags()

        for move, mls in self.grouped("move_id").items():
            if classification_before.get(move.id, (move.is_in, move.is_out)) != (
                move.is_in,
                move.is_out,
            ):
                move_to_update.add(move.id)
                continue
            if not (move.is_in or move.is_out):
                continue
            if move.is_in:
                move_to_update.add(move.id)
            elif move.is_out:
                delta = sum(
                    ml.quantity_product_uom - old_qty_by_ml.get(ml, 0)
                    for ml in mls
                    if not ml._should_exclude_for_valuation()
                )
                if delta:
                    move._set_value(correction_quantity=delta)
        if move_to_update:
            self.env["stock.move"].browse(move_to_update)._set_value()

    def _is_consigned_valued_line(self):
        return (
            self.picked
            and self._should_exclude_for_valuation()
            and (
                (
                    not self.location_id._should_be_valued()
                    and self.location_dest_id._should_be_valued()
                )
                or (
                    self.location_id._should_be_valued()
                    and not self.location_dest_id._should_be_valued()
                )
            )
        )
