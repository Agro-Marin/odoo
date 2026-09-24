from odoo import Command, api, fields, models
from odoo.libs.debug_log import DebugLog

_debug = DebugLog(__name__)


class StockBackorderConfirmationLine(models.TransientModel):
    _name = "stock.backorder.confirmation.line"
    _description = "Backorder Confirmation Line"

    backorder_confirmation_id = fields.Many2one(
        comodel_name="stock.backorder.confirmation"
    )
    picking_id = fields.Many2one(
        comodel_name="stock.picking",
        string="Transfer",
    )
    to_backorder = fields.Boolean()


class StockBackorderConfirmation(models.TransientModel):
    _name = "stock.backorder.confirmation"
    _inherit = ["mixin.stock.picking.validation"]
    _description = "Backorder Confirmation"

    pick_ids = fields.Many2many(
        comodel_name="stock.picking",
        relation="stock_picking_backorder_rel",
    )
    show_transfers = fields.Boolean()
    backorder_confirmation_line_ids = fields.One2many(
        comodel_name="stock.backorder.confirmation.line",
        inverse_name="backorder_confirmation_id",
        string="Backorder Confirmation Lines",
    )

    @api.model
    def default_get(self, fields):
        res = super().default_get(fields)
        if "backorder_confirmation_line_ids" in fields and res.get("pick_ids"):
            res["backorder_confirmation_line_ids"] = [
                Command.create({"to_backorder": True, "picking_id": pick_id})
                for pick_id in res["pick_ids"][0][2]
            ]
        return res

    def _check_less_quantities_than_expected(self, pickings):
        for pick_id in pickings:
            moves_to_log = {}
            for move in pick_id.move_ids:
                picked_qty = move._get_picked_quantity()
                if move.product_uom_id.compare(move.product_uom_qty, picked_qty) > 0:
                    moves_to_log[move] = (picked_qty, move.product_uom_qty)
            if moves_to_log:
                if _debug.logic.enabled:
                    _debug.logic(
                        "less_than_expected",
                        picking=pick_id.id,
                        move_ids=[move.id for move in moves_to_log],
                    )
                pick_id._log_less_quantities_than_expected(moves_to_log)

    def process(self):
        pickings_to_do = self.env["stock.picking"]
        pickings_not_to_do = self.env["stock.picking"]
        for line in self.backorder_confirmation_line_ids:
            if line.to_backorder is True:
                pickings_to_do |= line.picking_id
            else:
                pickings_not_to_do |= line.picking_id

        _debug.pipeline(
            "backorder_wizard_process",
            backorder=pickings_to_do,
            no_backorder=pickings_not_to_do,
            validate=self.validate_picking_ids,
        )
        if pickings_not_to_do and self._get_pickings_to_validate():
            self._check_less_quantities_than_expected(pickings_not_to_do)
        return self._resume_validation(
            skip_backorder=True,
            cancel_backorder_ids=self._get_cancel_backorder_ids(pickings_not_to_do),
        )

    def action_cancel_backorder(self):
        pickings_to_validate = self._get_pickings_to_validate()
        _debug.pipeline(
            "backorder_wizard_cancel",
            no_backorder=self.pick_ids,
            validate=pickings_to_validate,
        )
        if pickings_to_validate:
            self._check_less_quantities_than_expected(pickings_to_validate)
        return self._resume_validation(
            pickings_to_validate,
            skip_backorder=True,
            cancel_backorder_ids=self._get_cancel_backorder_ids(self.pick_ids),
        )

    def _get_cancel_backorder_ids(self, pickings):
        decided = (self.validate_kwargs or {}).get("cancel_backorder_ids") or []
        return [*decided, *pickings.ids]
