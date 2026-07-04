from odoo import api, models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    @api.depends(
        "reference_ids.sale_ids",
        "reference_ids.production_ids",
        "move_ids.sale_line_id.order_id",
    )
    def _compute_sale_id(self):
        # Redeclares sale_stock's full @api.depends list plus
        # reference_ids.production_ids: Odoo resolves ONE compute method
        # per name for the assembled model class (the last _inherit
        # definition wins), so the dependency graph is built from THIS
        # decorator. production_ids only exists once mrp is installed —
        # sale_mrp is the module that actually depends on both, which is
        # why the field-existence guard for _is_on_manufacturing_route()
        # lives here instead of in sale_stock directly.
        return super()._compute_sale_id()

    def _is_on_manufacturing_route(self):
        """A picking sharing a stock.reference with a manufacturing
        order is on a manufacturing route.

        See sale_stock.stock_picking._compute_sale_id: a multi-step
        (pbm_sam) MO's intermediate pickings carry no sale move of
        their own yet share the SO's stock.reference, so without this
        override they would be wrongly pulled into
        sale.order.picking_ids and break its singleton expectation.
        """
        self.ensure_one()
        return bool(self.reference_ids.production_ids)
