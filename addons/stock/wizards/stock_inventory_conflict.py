from odoo import fields, models

from ..tools import debug_log as dbg


class StockInventoryConflict(models.TransientModel):
    _name = "stock.inventory.conflict"
    _description = "Conflict in Inventory"

    quant_ids = fields.Many2many(
        comodel_name="stock.quant",
        relation="stock_conflict_quant_rel",
        string="Quants",
    )
    quant_to_fix_ids = fields.Many2many(
        comodel_name="stock.quant",
        string="Conflicts",
    )

    def action_keep_counted_quantity(self):
        dbg.logic.debug(
            "inventory conflict: keep counted on %s", dbg.rec(self.quant_ids)
        )
        for quant in self.quant_ids:
            quant.inventory_diff_quantity = quant.product_uom_id._round_aggregate(
                quant.inventory_quantity - quant.quantity
            )
        return self.quant_ids.action_apply_inventory(self._get_counting_date())

    def action_keep_difference(self):
        dbg.logic.debug(
            "inventory conflict: keep difference on %s", dbg.rec(self.quant_ids)
        )
        for quant in self.quant_ids:
            quant.inventory_quantity = quant.quantity + quant.inventory_diff_quantity
        return self.quant_ids.action_apply_inventory(self._get_counting_date())

    def _get_counting_date(self):
        return self.env.context.get("counting_date")
