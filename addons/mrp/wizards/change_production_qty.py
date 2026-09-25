from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.libs.debug_log import DebugLog

_debug = DebugLog(__name__)


class ChangeProductionQty(models.TransientModel):
    _name = "change.production.qty"
    _description = "Change Production Qty"

    mo_id = fields.Many2one(
        comodel_name="mrp.production",
        string="Manufacturing Order",
        required=True,
        ondelete="cascade",
    )
    product_qty = fields.Float(
        string="Quantity To Produce",
        digits="Product Unit",
        required=True,
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
        push_moves = self.env["stock.move"]
        open_moves = production.move_finished_ids.filtered(
            lambda move: move.state not in ("done", "cancel")
        )
        for move in open_moves:
            qty = (new_qty - old_qty) * move.unit_factor
            if self._is_quantity_propagation_required(move, qty):
                push_moves |= move.copy(
                    {"product_uom_qty": qty, "workorder_id": move.workorder_id.id}
                )
            else:
                move.write({"product_uom_qty": move.product_uom_qty + qty})

        _debug.pipeline(
            "finished_moves_rescaled",
            production=production.id,
            new_qty=new_qty,
            old_qty=old_qty,
            modified=len(open_moves),
            pushed=len(push_moves),
        )
        if push_moves:
            push_moves._action_confirm()
        production.move_finished_ids._action_assign()

    @api.model
    def _is_quantity_propagation_required(self, move, qty):
        return move.move_dest_ids and not move.product_uom_id.is_zero(qty)

    def change_prod_qty(self):
        for wizard in self:
            production = wizard.mo_id
            old_production_qty = production.product_qty
            new_production_qty = wizard.product_qty

            if production.state in ("done", "cancel"):
                _debug.logic("qty_change_refused", reason="closed", mo=production.id)
                raise UserError(
                    self.env._(
                        "%s is done or cancelled; its quantity can no longer change.",
                        production.display_name,
                    )
                )
            if production.product_uom_id.is_zero(old_production_qty):
                _debug.logic("qty_change_refused", mo=production)
                raise UserError(
                    self.env._(
                        "Cannot change the quantity of a manufacturing order whose "
                        "current quantity is zero."
                    )
                )
            factor = new_production_qty / old_production_qty
            _debug.lifecycle(
                "qty_changed", mo=production, old=old_production_qty, factor=factor
            )
            update_info = production._update_raw_moves(factor)
            documents = production._get_raw_moves_activity_documents(
                {move: (new_qty, old_qty) for move, old_qty, new_qty in update_info}
            )
            production._log_manufacture_exception(documents)
            self._update_finished_moves(
                production, new_production_qty, old_production_qty
            )
            producing_all = (
                production.product_uom_id.compare(
                    production.qty_producing, old_production_qty
                )
                == 0
            )
            production.write({"product_qty": new_production_qty})
            overflowing = (
                production.product_uom_id.compare(
                    production.qty_producing, new_production_qty
                )
                > 0
            )
            follows = producing_all and production.product_id.tracking != "serial"
            if (follows or overflowing) and not production.workorder_ids:
                production.qty_producing = new_production_qty
                production._update_moves_from_qty_producing()

            for wo in production.workorder_ids:
                remaining = wo.qty_production - wo.qty_produced
                if wo.product_uom_id.compare(remaining, 0) <= 0:
                    quantity = 0.0
                elif production.product_id.tracking == "serial":
                    quantity = 1.0
                else:
                    quantity = remaining
                wo._update_qty_producing(quantity)
                wo.duration_expected = wo._get_duration_expected(
                    ratio=new_production_qty / old_production_qty
                )
                if wo.state == "done" and not wo.is_produced:
                    wo.state = "progress"
                elif wo.state == "progress" and wo.is_produced:
                    wo.end_all()
                    wo.write(
                        {
                            "state": "done",
                            "date_end": fields.Datetime.now(),
                            "costs_hour": wo.workcenter_id.costs_hour,
                        }
                    )

        self.mo_id.filtered(
            lambda mo: mo.state in ["confirmed", "progress"]
        ).move_raw_ids._trigger_scheduler()

        return {}
