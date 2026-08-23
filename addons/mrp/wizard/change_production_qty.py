from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ChangeProductionQty(models.TransientModel):
    _name = "change.production.qty"
    _description = "Change Production Qty"

    mo_id = fields.Many2one(
        "mrp.production", "Manufacturing Order", required=True, ondelete="cascade"
    )
    product_qty = fields.Float(
        "Quantity To Produce", digits="Product Unit", required=True
    )

    @api.model
    def default_get(self, fields):
        res = super().default_get(fields)
        if (
            "mo_id" in fields
            and not res.get("mo_id")
            and self.env.context.get("active_model") == "mrp.production"
            and self.env.context.get("active_id")
        ):
            res["mo_id"] = self.env.context["active_id"]
        if "product_qty" in fields and not res.get("product_qty") and res.get("mo_id"):
            res["product_qty"] = (
                self.env["mrp.production"].browse(res["mo_id"]).product_qty
            )
        return res

    @api.model
    def _update_finished_moves(self, production, new_qty, old_qty):
        modification = {}
        push_moves = self.env["stock.move"]
        for move in production.move_finished_ids:
            if move.state in ("done", "cancel"):
                continue
            qty = (new_qty - old_qty) * move.unit_factor
            modification[move] = (move.product_uom_qty + qty, move.product_uom_qty)
            if self._need_quantity_propagation(move, qty):
                push_moves |= move.copy({"product_uom_qty": qty})
            else:
                move.write({"product_uom_qty": move.product_uom_qty + qty})

        if push_moves:
            push_moves._action_confirm()
        production.move_finished_ids._action_assign()

        return modification

    @api.model
    def _need_quantity_propagation(self, move, qty):
        return move.move_dest_ids and not move.product_uom_id.is_zero(qty)

    def change_prod_qty(self):
        precision = self.env["decimal.precision"].get_precision("Product Unit")
        activity_mixin = self.env["mixin.stock.activity"]
        for wizard in self:
            production = wizard.mo_id
            old_production_qty = production.product_qty
            new_production_qty = wizard.product_qty

            if production.product_uom_id.is_zero(old_production_qty):
                raise UserError(
                    _(
                        "Cannot change the quantity of a manufacturing order whose "
                        "current quantity is zero."
                    )
                )
            factor = new_production_qty / old_production_qty
            update_info = production._update_raw_moves(factor)
            documents = {}
            for move, old_qty, new_qty in update_info:
                iterate_key = production._get_document_iterate_key(move)
                if iterate_key:
                    document = activity_mixin._log_activity_get_documents(
                        {move: (new_qty, old_qty)}, iterate_key, "UP"
                    )
                    for key, value in document.items():
                        if documents.get(key):
                            documents[key] += [value]
                        else:
                            documents[key] = [value]
            production._log_manufacture_exception(documents)
            self._update_finished_moves(
                production, new_production_qty, old_production_qty
            )
            production.write({"product_qty": new_production_qty})
            if (
                not production.product_uom_id.is_zero(production.qty_producing)
                and not production.workorder_ids
            ):
                production.qty_producing = new_production_qty
                production._inverse_qty_producing()

            for wo in production.workorder_ids:
                operation = wo.operation_id
                # Rounded through the order's unit, like every other quantity test
                # in this method. The two tests this replaces read
                # `decimal_precision` instead, so a unit coarser than "Product
                # Unit" -- one that cannot be split at all -- called a remainder of
                # 0.4 non-zero and asked the work order to make 0.4 of an
                # indivisible thing. The sign is now handled once for both
                # branches: the serial one asked for one more unit on a *negative*
                # remainder, because `not float_is_zero(-3)` is true, while the
                # branch beside it had always guarded `quantity > 0`.
                remaining = wo.qty_production - wo.qty_produced
                if wo.product_uom_id.compare(remaining, 0) <= 0:
                    quantity = 0.0
                elif production.product_id.tracking == "serial":
                    quantity = 1.0
                else:
                    quantity = remaining
                wo._update_qty_producing(quantity)
                # After `_update_qty_producing`, not before.  A work order that
                # carries an operation derives its duration from the quantity,
                # and asking for it first read the *old* `qty_producing`: a
                # started work order taken from 5 to 20 kept the 50 minutes it
                # was scheduled for, four times short, while the same call one
                # line later returns 200.  `ratio` never reached that branch --
                # it is read only by the operation-less one, which still needs
                # it because it has no quantity-driven formula to fall back on.
                wo.duration_expected = wo._get_duration_expected(
                    ratio=new_production_qty / old_production_qty
                )
                # `is_produced`, not a pair of bare float comparisons. The two
                # tests here were `<` and `==`, which are not complements: a work
                # order that had produced *more* than the order now asks for
                # satisfied neither and stayed at `progress` for good -- which is
                # exactly what cutting an order below what is already made
                # produces. `mrp.workorder.is_produced` is the model's own answer
                # to this question, rounded through the order's unit.
                if wo.state == "done" and not wo.is_produced:
                    wo.state = "progress"
                elif wo.state == "progress" and wo.is_produced:
                    wo.state = "done"
                moves_raw = production.move_raw_ids.filtered(
                    lambda move, operation=operation: (
                        move.operation_id == operation
                        and move.state not in ("done", "cancel")
                    )
                )
                if wo == production.workorder_ids[-1]:
                    moves_raw |= production.move_raw_ids.filtered(
                        lambda move: not move.operation_id
                    )
                moves_finished = production.move_finished_ids.filtered(
                    lambda move, operation=operation: move.operation_id == operation
                )
                moves_raw.mapped("move_line_ids").write({"workorder_id": wo.id})
                (moves_finished + moves_raw).write({"workorder_id": wo.id})

        self.mo_id.filtered(
            lambda mo: mo.state in ["confirmed", "progress"]
        ).move_raw_ids._trigger_scheduler()

        return {}
