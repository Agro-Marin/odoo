from collections import defaultdict

from odoo import api, fields, models


class StockLot(models.Model):
    "Inherit StockLot"

    _inherit = "stock.lot"

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    sale_order_ids = fields.Many2many(
        comodel_name="sale.order",
        string="Sales Orders",
        compute="_compute_sale_order_ids",
        readonly=True,
    )
    count_sale_order = fields.Integer(
        string="Sale order count",
        compute="_compute_sale_order_ids",
    )

    # ------------------------------------------------------------
    # COMPUTE METHODS
    # ------------------------------------------------------------

    @api.depends("name")
    def _compute_sale_order_ids(self):
        sale_orders = defaultdict(lambda: self.env["sale.order"])
        sml = self.env["stock.move.line"].search(
            [("lot_id", "in", self.ids), ("state", "=", "done")]
        )
        for move_line in sml:
            move = move_line.move_id
            if (
                move.picking_id.location_dest_id.usage in ("customer", "transit")
                and move.sale_line_id.order_id
            ):
                sale_orders[move_line.lot_id.id] |= move.sale_line_id.order_id
        for lot in self:
            lot.sale_order_ids = sale_orders[lot.id]
            lot.count_sale_order = len(lot.sale_order_ids)

    # ------------------------------------------------------------
    # ACTIONS
    # ------------------------------------------------------------

    def action_view_so(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id("sale.action_orders")
        action["domain"] = [("id", "in", self.mapped("sale_order_ids.id"))]
        action["context"] = dict(self._context, create=False)
        return action
