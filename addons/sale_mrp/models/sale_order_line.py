from odoo import api, models
from odoo.libs.debug_log import DebugLog

_debug = DebugLog(__name__)


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    def _compute_display_qty_widget(self):
        super()._compute_display_qty_widget()
        lines = self.filtered(
            lambda line: line.product_id and line.product_id.is_storable
        )
        boms_per_line = lines._get_phantom_bom_per_line()

        for line in lines:
            if boms_per_line[line][1]:
                line.display_qty_widget = False
                continue

            if line.state == "draft" and line.product_type == "consu":
                components = line.product_id._get_components()
                if components and components != line.product_id:
                    line.display_qty_widget = True

    def compute_uom_qty(self, new_qty, stock_move, rounding=True):
        bom_line = stock_move.bom_line_id
        if not bom_line:
            return super().compute_uom_qty(new_qty, stock_move, rounding)
        kit_qty = self.product_uom_id._get_quantity_in_unit(
            new_qty, bom_line.bom_id.product_uom_id, rounding
        )
        component_qty = kit_qty * bom_line.product_qty / bom_line.bom_id.product_qty
        return bom_line.product_uom_id._get_quantity_in_unit(
            component_qty, stock_move.product_uom_id, rounding
        )

    @api.model
    def _get_incoming_outgoing_moves_filter(self):
        sorted_moves = self.move_ids.sorted("id")
        triggering_rule_ids = []
        seen_wh_ids = set()
        seen_bom_id = set()
        for move in sorted_moves:
            if move.bom_line_id.bom_id.id in seen_bom_id:
                triggering_rule_ids.append(move.rule_id.id)
            elif move.warehouse_id.id not in seen_wh_ids:
                triggering_rule_ids.append(move.rule_id.id)
                seen_wh_ids.add(move.warehouse_id.id)
                if move.bom_line_id and move.bom_line_id.bom_id.type == "phantom":
                    seen_bom_id.add(move.bom_line_id.bom_id.id)

        return {
            "incoming_moves": lambda m: (
                m.state != "cancel"
                and m.location_dest_usage != "inventory"
                and m.rule_id.id in triggering_rule_ids
                and m.location_final_id.usage == "customer"
                and (
                    not m.origin_returned_move_id
                    or (m.origin_returned_move_id and m.to_refund)
                )
            ),
            "outgoing_moves": lambda m: (
                m.state != "cancel"
                and m.location_dest_usage != "inventory"
                and m.location_id.usage == "customer"
                and m.to_refund
            ),
        }

    def _get_procurement_qty(self, previous_product_qty=False):
        self.check_singleton()
        bom = (
            self.env["mrp.bom"]
            .sudo()
            ._get_bom_by_product(
                self.product_id, bom_type="phantom", company_id=self.company_id.id
            )[self.product_id]
        )
        if bom and self.move_ids:
            _debug.logic("procurement_qty", line=self, by="kit_bom", bom=bom)
            moves = self.move_ids.filtered(
                lambda r: r.state != "cancel" and r.location_dest_usage != "inventory"
            )
            filters = self._get_incoming_outgoing_moves_filter()
            order_qty = (
                previous_product_qty.get(self.id, 0)
                if previous_product_qty
                else self.product_qty
            )
            order_qty = self.product_uom_id._get_quantity_in_unit(
                order_qty, bom.product_uom_id
            )
            qty = moves._get_kit_quantity(self.product_id, order_qty, bom, filters)
            return bom.product_uom_id._get_quantity_in_unit(qty, self.product_uom_id)
        elif bom and previous_product_qty:
            return previous_product_qty.get(self.id)
        return super()._get_procurement_qty(previous_product_qty=previous_product_qty)
