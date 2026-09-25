from odoo import api, fields, models


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    mrp_production_count = fields.Integer(
        string="Count of MO Source",
        compute="_compute_mrp_production_count",
        groups="mrp.group_mrp_user",
    )

    @api.depends(
        "line_ids.move_dest_ids.raw_material_production_id",
        "line_ids.move_ids.move_dest_ids.raw_material_production_id",
    )
    def _compute_mrp_production_count(self):
        for purchase in self:
            purchase.mrp_production_count = len(purchase._get_mrp_productions())

    def _get_mrp_productions(self, **kwargs):
        return (
            self.line_ids.move_dest_ids | self.line_ids.move_ids.move_dest_ids
        ).raw_material_production_id

    def action_view_mrp_productions(self):
        self.check_singleton()
        mrp_production_ids = self._get_mrp_productions().ids
        action = {
            "res_model": "mrp.production",
            "type": "ir.actions.act_window",
        }
        if len(mrp_production_ids) == 1:
            action.update(
                {
                    "view_mode": "form",
                    "res_id": mrp_production_ids[0],
                }
            )
        else:
            action.update(
                {
                    "name": self.env._("Manufacturing Source of %s", self.name),
                    "domain": [("id", "in", mrp_production_ids)],
                    "view_mode": "list,form",
                }
            )
        return action


class PurchaseOrderLine(models.Model):
    _inherit = "purchase.order.line"

    def _prepare_stock_move_vals_list(self, picking):
        res = super()._prepare_stock_move_vals_list(picking)
        if len(self.order_id.reference_ids.move_ids.production_group_id) == 1:
            for re in res:
                re["production_group_id"] = (
                    self.order_id.reference_ids.move_ids.production_group_id.id
                )
        sale_line_product = self._get_sale_order_line_product()
        if sale_line_product:
            bom = self.env["mrp.bom"]._get_bom_by_product(
                self.env["product.product"].browse(sale_line_product.id),
                company_id=picking.company_id.id,
                bom_type="phantom",
            )
            bom_kit = bom.get(sale_line_product)
            if bom_kit:
                _dummy, bom_sub_lines = bom_kit._explode(
                    sale_line_product, self.sale_line_id.product_uom_qty
                )
                bom_kit_component = {
                    line["product_id"].id: line.id for line, _ in bom_sub_lines
                }
                for vals in res:
                    if vals["product_id"] in bom_kit_component:
                        vals["bom_line_id"] = bom_kit_component[vals["product_id"]]
        return res

    def _get_upstream_documents_and_responsibles(self, visited):
        return [(self.order_id, self.order_id.user_id, visited)]

    def _get_procurement_qty(self, previous_product_qty=False):
        self.check_singleton()
        if (
            "previous_product_qty" in self.env.context
            and (
                self.env["mrp.bom"]
                .sudo()
                ._get_bom_by_product(
                    self.product_id, bom_type="phantom", company_id=self.company_id.id
                )[self.product_id]
            )
        ):
            return self.env.context["previous_product_qty"].get(self.id, 0.0)
        return super()._get_procurement_qty(previous_product_qty=previous_product_qty)

    def _get_stock_move_dests_initial_demand(self, move_dests):
        kit_bom = self.env["mrp.bom"]._get_bom_by_product(
            self.product_id, bom_type="phantom", company_id=self.company_id.id
        )[self.product_id]
        if kit_bom:
            filters = {
                "incoming_moves": lambda m: True,
                "outgoing_moves": lambda m: False,
            }
            return move_dests._get_kit_quantity(
                self.product_id, self.product_qty, kit_bom, filters
            )
        return super()._get_stock_move_dests_initial_demand(move_dests)

    def _get_sale_order_line_product(self):
        return False
