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
        # `picked` belongs here: `_get_in_move_lines` / `_get_out_move_lines` skip
        # unpicked lines, so it decides whether -- and in which direction -- the move
        # is valued, exactly like the owner and the locations below. Without it,
        # unticking `picked` on a done move (a stored, writable field whose inverse
        # pushes down to the lines, and an editable column on a done picking) left
        # `is_in`/`is_out`/`value` describing move lines that no longer exist: stock
        # stayed on hand valued at 0, or a re-averaged cost doubled.
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
            # In the product's UoM, like every other quantity the valuation deals
            # in: a line's `product_uom_id` is a writable compute that only
            # *defaults* to its move's, so `quantity` here and `move.quantity` on
            # the other side of the correction are not necessarily the same unit.
            qty_by_ml = {
                ml: ml.quantity_product_uom
                for ml in self
                if ml.move_id.is_in or ml.move_id.is_out
            }
        res = super().write(vals)
        if valuation_trigger:
            # Not `and qty_by_ml`: that map is empty precisely when none of these
            # moves was valued yet, which is the case where the write may be what
            # starts valuing one (clearing a consignment owner, for instance).
            self._update_stock_move_value(qty_by_ml)
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

    @api.model
    def _should_exclude_for_valuation(self):
        """
        Determines if this move line should be excluded from valuation based on its ownership.
        :return: True if the move line's owner is different from the company's partner (indicating
                it should be excluded from valuation), False otherwise.
        """
        self.ensure_one()
        return self.owner_id and self.owner_id != self.company_id.partner_id

    def _update_stock_move_value(self, old_qty_by_ml=None):
        move_to_update = set()
        if not old_qty_by_ml:
            old_qty_by_ml = {}

        # The caller just changed a field that decides whether -- and in which
        # direction -- these moves are valued (owner, locations, picked). The stored
        # flags were derived when the move was done and cannot see that, so record
        # what they said, then re-derive: read stale, this method would revalue a
        # move that has stopped being valued, or skip one that has started.
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
                # The move changed side (or stopped being valued): its stored value
                # was computed for the old classification, so scaling it by a
                # quantity delta would carry that meaning forward. Re-derive it.
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
        """return true if the move line would have been considered in the _get_valued_qty() method except for
        the _should_exclude_for_valuation criteria (.i.e the line would have been valued if it wasn't consigned)
        """
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
