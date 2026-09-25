from collections import defaultdict

from odoo import fields, models
from odoo.libs.debug_log import DebugLog
from odoo.tools import OrderedSet, float_compare

from odoo.addons.trade.tools import direction_of

_debug = DebugLog(__name__)


class MixinOrderLineStock(models.AbstractModel):
    _inherit = "mixin.order.line.stock"

    def _compute_qty_transferred(self):
        kit_qties = self._get_kit_lines_transferred_qty()
        for line, qty in kit_qties.items():
            line.qty_transferred = qty
        super(
            MixinOrderLineStock, self - self.browse().concat(*kit_qties)
        )._compute_qty_transferred()

    def _prepare_qty_transferred(self):
        kit_qties = self._get_kit_lines_transferred_qty()
        transferred_qties = super(
            MixinOrderLineStock, self - self.browse().concat(*kit_qties)
        )._prepare_qty_transferred()
        transferred_qties.update(kit_qties)
        return transferred_qties

    def _get_kit_lines_transferred_qty(self):
        boms_per_line = self._get_kit_bom_per_line()
        _debug.perf.count("kit_bom_lines", lines=len(self), kits=len(boms_per_line))
        return {
            line: line._get_kit_transferred_qty(*boms)
            for line, boms in boms_per_line.items()
        }

    def _get_kit_bom_per_line(self):
        from_stock = self.filtered(
            lambda line: line.qty_transferred_method == "stock_move"
        )
        from_stock.fetch(["move_ids"])
        candidates = from_stock.filtered("move_ids")
        return {
            line: boms
            for line, boms in candidates._get_phantom_bom_per_line(retry=True).items()
            if any(boms)
        }

    def _get_phantom_bom_per_line(self, retry=False):
        products_per_company = defaultdict(OrderedSet)
        for line in self:
            products_per_company[line.company_id].add(line.product_id.id)
        found_per_company = {}

        def get_bom(line):
            company = line.company_id
            if company not in found_per_company:
                found_per_company[company] = self.env["mrp.bom"]._get_bom_by_product(
                    self.env["product.product"].browse(products_per_company[company]),
                    company_id=company.id,
                    bom_type="phantom",
                )
            return found_per_company[company].get(line.product_id, self.env["mrp.bom"])

        result = {}
        for line in self:
            if line.state == "draft":
                boms = get_bom(line)
            elif line.state == "done":
                boms = line.move_ids.filtered(
                    lambda move: move.state != "cancel"
                ).bom_line_id.bom_id
            else:
                boms = self.env["mrp.bom"]
            relevant_bom = boms.filtered(line._is_own_phantom_bom)
            if not relevant_bom and retry:
                relevant_bom = get_bom(line)
                _debug.logic("phantom_bom_retried", line=line, bom=relevant_bom)
            result[line] = (boms, relevant_bom)
        return result

    def _is_own_phantom_bom(self, bom):
        self.check_singleton()
        return bom.type == "phantom" and (
            bom.product_id == self.product_id
            or (
                bom.product_tmpl_id == self.product_id.product_tmpl_id
                and not bom.product_id
            )
        )

    def _get_kit_transferred_qty(self, boms, kit_bom):
        self.check_singleton()
        if any(move._is_dropshipped() for move in self.move_ids):
            _debug.logic("kit_qty", line=self, by="dropship")
            return self._get_dropshipped_kit_qty()

        if not kit_bom:
            direction = direction_of(self)
            moves = self._get_kit_moves(include_cancelled=True)
            transferred = bool(moves) and all(
                move.state == "done"
                and move[direction.partner_location_field].usage
                == direction.partner_usage
                for move in moves
            )
            _debug.logic("kit_qty", line=self, by="no_bom", transferred=transferred)
            return self.product_qty if transferred else 0.0

        moves = self._get_kit_moves().filtered(
            lambda move: (
                move.state == "done" and move.location_dest_usage != "inventory"
            )
        )
        order_qty = self.product_uom_id._get_quantity_reconcile(
            self.product_qty, kit_bom.product_uom_id
        )
        qty_transferred = moves._get_kit_quantity(
            self.product_id, order_qty, kit_bom, self._get_kit_moves_filter()
        )
        _debug.logic(
            "kit_qty", line=self, by="bom_components", bom=kit_bom, qty=qty_transferred
        )
        return kit_bom.product_uom_id._get_quantity_reconcile(
            qty_transferred, self.product_uom_id
        )

    def _get_dropshipped_kit_qty(self):
        self.check_singleton()
        moves = self._get_kit_moves()
        if not moves:
            return 0.0
        for move in moves:
            if move.location_dest_id.usage == "customer":
                if move.state != "done":
                    return 0.0
                continue
            returned_qty = sum(
                returned.product_uom_id._get_quantity_reconcile(
                    returned.quantity, move.product_uom_id
                )
                for returned in move.returned_move_ids
                if returned.state == "done"
            )
            if (
                move.state == "done"
                and float_compare(
                    move.quantity,
                    returned_qty,
                    precision_rounding=move.product_uom_id.rounding,
                )
                > 0
            ):
                return 0.0
        return self.product_qty

    def _get_kit_moves(self, include_cancelled=False):
        self.check_singleton()
        moves = self.move_ids
        if not include_cancelled:
            moves = moves.filtered(lambda move: move.state != "cancel")
        accrual_date = self.env.context.get("accrual_entry_date")
        if not accrual_date:
            return moves
        accrual_date = fields.Date.from_string(accrual_date)
        return moves.filtered(
            lambda move: fields.Date.context_today(move, move.date) <= accrual_date
        )

    def _get_kit_moves_filter(self):
        toward_partner = direction_of(self).partner_side == "destination"

        def forward(move):
            return move._is_outgoing() if toward_partner else move._is_incoming()

        def backward(move):
            return move._is_incoming() if toward_partner else move._is_outgoing()

        return {
            "incoming_moves": lambda move: (
                forward(move) and (not move.origin_returned_move_id or move.to_refund)
            ),
            "outgoing_moves": lambda move: backward(move) and move.to_refund,
        }
