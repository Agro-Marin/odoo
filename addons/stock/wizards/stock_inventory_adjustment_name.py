from odoo import fields, models
from odoo.libs.debug_log import DebugLog

_debug = DebugLog(__name__)


class StockInventoryAdjustmentName(models.TransientModel):
    _name = "stock.inventory.adjustment.name"
    _description = "Inventory Adjustment Reference / Reason"

    quant_ids = fields.Many2many(comodel_name="stock.quant")
    inventory_adjustment_name = fields.Char(
        string="Inventory Reason",
        default="Physical Inventory",
    )
    counting_date = fields.Datetime(
        default=fields.Datetime.now,
        help="Date at which the resulting moves will be dated.",
    )

    def _prepare_quants_context(self):
        return {
            "inventory_name": self.inventory_adjustment_name,
            "counting_date": self.counting_date,
        }

    def action_apply(self):
        quants = self.quant_ids.filtered("inventory_quantity_set")
        _debug.pipeline(
            "inventory_adjustment",
            name=self.inventory_adjustment_name,
            quants=quants,
            selected=len(self.quant_ids),
        )
        return quants.with_context(
            self._prepare_quants_context()
        ).action_apply_inventory(self.counting_date)
