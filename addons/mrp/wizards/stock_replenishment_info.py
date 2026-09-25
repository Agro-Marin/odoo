from odoo import api, fields, models


class StockReplenishmentInfo(models.TransientModel):
    _inherit = "stock.replenishment.info"
    _description = "Stock supplier replenishment information"

    bom_id = fields.Many2one(related="orderpoint_id.bom_id")
    bom_ids = fields.Many2many(
        comodel_name="mrp.bom",
        compute="_compute_bom_ids",
        store=True,
    )
    show_bom_tab = fields.Boolean(compute="_compute_show_bom_tab")

    @api.depends("orderpoint_id", "product_id")
    def _compute_bom_ids(self):
        for replenishment_info in self:
            product = replenishment_info.product_id
            replenishment_info.bom_ids = (
                product.product_tmpl_id.bom_ids.filtered_domain(
                    [
                        ("type", "=", "normal"),
                        ("product_id", "in", [product.id, False]),
                        (
                            "company_id",
                            "in",
                            [replenishment_info.orderpoint_id.company_id.id, False],
                        ),
                    ]
                )
            )

    @api.depends("orderpoint_id")
    def _compute_show_bom_tab(self):
        for replenishment_info in self:
            orderpoint = replenishment_info.orderpoint_id
            replenishment_info.show_bom_tab = not orderpoint.route_id or (
                orderpoint.route_id
                and "manufacture" in orderpoint.rule_ids.mapped("action")
            )
