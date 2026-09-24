from odoo import Command, models
from odoo.tools.misc import clean_context

from ..tools import debug_log as dbg
from .stock_picking import DONE_CANCEL_STATES


class StockPickingBackorder(models.Model):
    _inherit = "stock.picking"

    def _split_backorder_pickings(self, cancel_backorder_pickings=None):
        not_to_backorder = self.filtered(
            lambda p: p.picking_type_id.create_backorder == "never",
        )
        if cancel_backorder_pickings:
            not_to_backorder |= (cancel_backorder_pickings & self).filtered(
                lambda p: p.picking_type_id.create_backorder != "always"
            )
        dbg.logic.debug(
            "_split_backorder_pickings: backorder %s, no backorder %s",
            dbg.rec(self - not_to_backorder),
            dbg.rec(not_to_backorder),
        )
        return self - not_to_backorder, not_to_backorder

    def _prepare_action_backorder_confirmation(
        self, show_transfers=False, *, validating=None, validate_kwargs=None
    ):
        view = self.env.ref("stock.view_backorder_confirmation")
        validating = self if validating is None else validating
        return {
            "name": self.env._("Create Backorder?"),
            "type": "ir.actions.act_window",
            "view_mode": "form",
            "res_model": "stock.backorder.confirmation",
            "views": [(view.id, "form")],
            "view_id": view.id,
            "target": "new",
            "context": {
                **clean_context(self.env.context),
                **validating._get_validation_resume_defaults(validate_kwargs),
                "default_show_transfers": show_transfers,
                "default_pick_ids": [Command.link(p.id) for p in self],
            },
        }

    def _prepare_backorder_picking_vals(self):
        self.check_singleton()
        return self.copy_data(
            {
                "name": "/",
                "move_ids": [],
                "move_line_ids": [],
                "backorder_id": self.id,
                "return_id": self.return_id.id,
            },
        )[0]

    def _post_create_backorder(self, backorder):
        pass

    @dbg.timed
    def _create_backorder(self, backorder_moves=None):
        self._detach_from_batch_before_backorder()
        moves_by_picking = {}
        backorder_moves_by_picking = (
            backorder_moves.grouped("picking_id") if backorder_moves else {}
        )
        for picking in self:
            if backorder_moves:
                moves_to_backorder = backorder_moves_by_picking.get(
                    picking, backorder_moves.browse()
                )
            else:
                moves_to_backorder = picking._get_moves_to_backorder()
            if moves_to_backorder:
                moves_by_picking[picking] = moves_to_backorder
        if not moves_by_picking:
            return self.browse()

        sources = self.browse([picking.id for picking in moves_by_picking])
        backorders = self.create(
            [picking._prepare_backorder_picking_vals() for picking in sources],
        )
        dbg.pipeline.debug(
            "_create_backorder: %s -> %s with moves %s",
            dbg.rec(sources),
            dbg.rec(backorders),
            {p.id: moves.ids for p, moves in moves_by_picking.items()},
        )

        bo_to_assign = self.browse()
        all_moves_to_backorder = self.env["stock.move"]
        for picking, backorder_picking in zip(sources, backorders, strict=True):
            picking._post_create_backorder(backorder_picking)
            moves_to_backorder = moves_by_picking[picking]
            moves_to_backorder.write(
                {"picking_id": backorder_picking.id, "picked": False},
            )
            moves_to_backorder.move_line_ids.write(
                {"picking_id": backorder_picking.id},
            )
            all_moves_to_backorder |= moves_to_backorder
            picking.message_post(
                body=self.env._(
                    "The backorder %s has been created.",
                    backorder_picking._get_html_link(),
                ),
            )
            if backorder_picking.picking_type_id.reservation_method == "at_confirm":
                bo_to_assign |= backorder_picking
        backorders.user_id = False
        all_moves_to_backorder._recompute_state()
        if bo_to_assign:
            dbg.pipeline.debug(
                "_create_backorder -> action_assign at_confirm %s",
                dbg.rec(bo_to_assign),
            )
            bo_to_assign.action_assign()
        return backorders

    def _get_moves_to_backorder(self):
        self.check_singleton()
        return self.move_ids.filtered(lambda x: x.state not in DONE_CANCEL_STATES)

    def _get_pickings_to_confirm_backorder(self):
        backorder_pickings = self.browse()
        for picking in self:
            if picking.picking_type_id.create_backorder != "ask":
                continue
            if any(
                (move.product_uom_qty and not move.picked)
                or move.product_uom_id.compare(
                    move._get_picked_quantity(),
                    move.product_uom_qty,
                )
                < 0
                for move in picking.move_ids
                if move.state != "cancel"
            ):
                backorder_pickings |= picking
        dbg.logic.debug(
            "_get_pickings_to_confirm_backorder: %s", dbg.rec(backorder_pickings)
        )
        return backorder_pickings

    def _is_backorder_ignore_required(self):
        return bool(self.return_id)

    def _log_less_quantities_than_expected(self, moves):
        def get_picking_responsible_key(move):
            return (move.picking_id, move.product_id.responsible_id)

        def _render_note_exception_quantity(document):
            origin_picking = self.env["stock.move"].concat(*document.changes).picking_id
            impacted_pickings = (
                origin_picking._get_impacted_pickings(document.records)
                - document.records.picking_id
            )
            values = {
                "origin_picking": origin_picking,
                "moves_information": document.changes.items(),
                "impacted_pickings": impacted_pickings,
            }
            return self.env["ir.qweb"]._render("stock.exception_on_picking", values)

        documents = self._get_log_activity_documents(
            moves,
            "move_dest_ids",
            "DOWN",
            get_picking_responsible_key,
        )
        documents = self._add_less_quantities_than_expected_documents(moves, documents)
        self._log_activity(_render_note_exception_quantity, documents)

    def _add_less_quantities_than_expected_documents(self, moves, documents):
        return documents

    def _get_without_quantities_error_message(self):
        return self.env._(
            "Transfer trouble alert! Validating a zero quantity transfer? You're not moving invisible goods around are you?\n"
            "Set some quantities and let's get moving!",
        )

    def _is_transfer_display_required(self, batch=None):
        detached = self._get_pickings_detached_from_batch(batch)
        if len(self.batch_id) == 1 and self == self.batch_id.picking_ids - detached:
            return False
        return len(self) > 1
