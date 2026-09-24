from odoo import models
from odoo.libs.debug_log import DebugLog

_debug = DebugLog(__name__)


class MixinStockConsignment(models.AbstractModel):
    _name = "mixin.stock.consignment"
    _description = "Set of Moves Handled as One Shipment"

    def _get_consignment_pickings(self):
        raise NotImplementedError

    def _get_consignment_moves(self):
        return self.move_ids

    def _get_consignment_move_lines(self):
        return self.move_line_ids

    def _get_consignment_partners(self):
        partners = self._get_consignment_pickings().partner_id
        _debug.logic("consignment_partners", consignment=self, partners=partners)
        return partners

    @_debug.perf.timed
    def _get_consignment_weight(self):
        lines = self._get_consignment_move_lines()
        weight = sum(
            line.product_id.weight * line.quantity_product_uom for line in lines
        )
        _debug.logic(
            "consignment_weight", consignment=self, weight=weight, lines=len(lines)
        )
        return weight
