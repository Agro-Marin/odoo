from odoo import fields, models

from ..tools import debug_log as dbg


class StockInventoryWarning(models.TransientModel):
    _name = "stock.inventory.warning"
    _description = "Inventory Adjustment Warning"

    quant_ids = fields.Many2many(comodel_name="stock.quant")

    def action_reset(self):
        return self.quant_ids.action_clear_inventory_quantity()

    def action_set(self):
        valid_quants = self.quant_ids.filtered(
            lambda quant: not quant.inventory_quantity_set
        )
        dbg.logic.debug(
            "inventory warning: set on %s of %d",
            dbg.rec(valid_quants),
            len(self.quant_ids),
        )
        return valid_quants.action_set_inventory_quantity()
