from odoo import fields, models


class TestTradeStockOrderLine(models.Model):
    _name = "test_trade_stock.order.line"
    _inherit = ["mixin.order.line.stock"]
    _description = "Base Order Stock Test Order Line"

    state = fields.Selection(
        selection=[("draft", "Draft"), ("done", "Done")],
        default="draft",
    )
    display_type = fields.Selection(
        selection=[("line_section", "Section"), ("line_note", "Note")]
    )
    product_qty = fields.Float()
    qty_transferred = fields.Float()
