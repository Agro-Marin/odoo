from odoo import api, models


class ChangeProductionQty(models.TransientModel):
    _inherit = "change.production.qty"

    @api.model
    def _is_quantity_propagation_required(self, move, qty):
        res = super()._is_quantity_propagation_required(move, qty)
        return res and not any(m.is_subcontract for m in move.move_dest_ids)
