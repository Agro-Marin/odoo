from odoo import models


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
        return self._get_consignment_pickings().partner_id

    def _get_consignment_weight(self):
        return sum(
            line.product_id.weight * line.quantity_product_uom
            for line in self._get_consignment_move_lines()
        )
