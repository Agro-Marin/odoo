from odoo import api, fields, models
from odoo.osv.expression import AND
from odoo.tools.translate import _


class StockWarehouseOrderpoint(models.Model):
    "Inherit StockWarehouseOrderpoint"

    _inherit = "stock.warehouse.orderpoint"

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    product_supplier_id = fields.Many2one(
        comodel_name="res.partner",
        string="Product Supplier",
        compute="_compute_product_supplier_id",
        store=True,
    )
    show_supplier = fields.Boolean(
        string="Show supplier column",
        compute="_compute_show_suppplier",
    )
    supplier_id = fields.Many2one(
        comodel_name="product.supplierinfo",
        string="Supplier",
        check_company=True,
        domain="""[
            '|',
            ('product_id', '=', product_id),
            '&',
            ('product_id', '=', False),
            ('product_tmpl_id', '=', product_tmpl_id)
        ]""",
    )
    vendor_id = fields.Many2one(related="supplier_id.partner_id", string="Vendor",)
    purchase_visibility_days = fields.Float(
        default=0.0,
        help="Visibility Days applied on the purchase routes.",
    )

    # ------------------------------------------------------------
    # COMPUTE METHODS
    # ------------------------------------------------------------

    def _compute_visibility_days(self):
        res = super()._compute_visibility_days()
        for orderpoint in self:
            if "buy" in orderpoint.rule_ids.mapped("action"):
                orderpoint.visibility_days = orderpoint.purchase_visibility_days
        return res

    @api.depends(
        "product_id.purchase_order_line_ids.product_qty",
        "product_id.purchase_order_line_ids.state",
    )
    def _compute_qty(self):
        """Extend to add more depends values"""
        return super()._compute_qty()

    @api.depends("supplier_id")
    def _compute_lead_days(self):
        return super()._compute_lead_days()

    @api.depends(
        "product_tmpl_id",
        "product_tmpl_id.seller_ids",
        "product_tmpl_id.seller_ids.sequence",
        "product_tmpl_id.seller_ids.partner_id",
    )
    def _compute_product_supplier_id(self):
        for orderpoint in self:
            orderpoint.product_supplier_id = (
                orderpoint.product_tmpl_id.seller_ids.sorted("sequence")[
                    :1
                ].partner_id.id
            )

    @api.depends("route_id")
    def _compute_show_suppplier(self):
        buy_route = []
        for res in self.env["stock.rule"].search_read(
            [("action", "=", "buy")], ["route_id"]
        ):
            buy_route.append(res["route_id"][0])
        for orderpoint in self:
            orderpoint.show_supplier = orderpoint.route_id.id in buy_route

    def _set_default_route_id(self):
        route_ids = self.env["stock.rule"].search([("action", "=", "buy")]).route_id
        for orderpoint in self:
            route_id = orderpoint.rule_ids.route_id & route_ids
            if not orderpoint.product_id.seller_ids:
                continue

            if not route_id:
                continue

            orderpoint.route_id = route_id[0].id
        return super()._set_default_route_id()

    def _set_visibility_days(self):
        res = super()._set_visibility_days()
        for orderpoint in self:
            if "buy" in orderpoint.rule_ids.mapped("action"):
                orderpoint.purchase_visibility_days = orderpoint.visibility_days
        return res

    def _compute_days_to_order(self):
        res = super()._compute_days_to_order()
        # Avoid computing rule_ids if no stock.rules with the buy action
        if not self.env["stock.rule"].search([("action", "=", "buy")]):
            return res

        # Compute rule_ids only for orderpoint whose
        # company_id.days_to_purchase != orderpoint.days_to_order
        orderpoints_to_compute = self.filtered(
            lambda orderpoint: orderpoint.days_to_order
            != orderpoint.company_id.days_to_purchase
        )
        for orderpoint in orderpoints_to_compute:
            if "buy" in orderpoint.rule_ids.mapped("action"):
                orderpoint.days_to_order = orderpoint.company_id.days_to_purchase
        return res

    def action_view_purchase(self):
        """This function returns an action that display existing
        purchase orders of given orderpoint."""
        result = self.env["ir.actions.act_window"]._for_xml_id("purchase.purchase_rfq")
        # Remvove the context since the action basically display RFQ and not PO.
        result["context"] = {}
        line_ids = self.env["purchase.order.line"].search(
            [("orderpoint_id", "=", self.id)]
        )
        purchase_ids = line_ids.mapped("order_id")
        result["domain"] = "[('id', 'in', %s)]" % (purchase_ids.ids)
        return result

    def _get_lead_days_values(self):
        values = super()._get_lead_days_values()
        if self.supplier_id:
            values["supplierinfo"] = self.supplier_id
        return values

    def _get_replenishment_order_notification(self):
        self.ensure_one()
        domain = [("orderpoint_id", "in", self.ids)]
        if self.env.context.get("written_after"):
            domain = AND(
                [domain, [("write_date", ">=", self.env.context.get("written_after"))]]
            )
        order = self.env["purchase.order.line"].search(domain, limit=1).order_id
        if order:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("The following replenishment order has been generated"),
                    "message": "%s",
                    "links": [
                        {
                            "label": order.display_name,
                            "url": f"/odoo/action-purchase.action_rfq_form/{order.id}",
                        }
                    ],
                    "sticky": False,
                    "next": {"type": "ir.actions.act_window_close"},
                },
            }
        return super()._get_replenishment_order_notification()

    def _prepare_procurement_values(self, date=False, group=False):
        values = super()._prepare_procurement_values(date=date, group=group)
        values["supplierinfo_id"] = self.supplier_id
        return values

    def _quantity_in_progress(self):
        res = super()._quantity_in_progress()
        qty_by_product_location, dummy = self.product_id._get_quantity_in_progress(
            self.location_id.ids
        )
        for orderpoint in self:
            product_qty = qty_by_product_location.get(
                (orderpoint.product_id.id, orderpoint.location_id.id), 0.0
            )
            product_uom_qty = orderpoint.product_id.uom_id._compute_quantity(
                product_qty, orderpoint.product_uom, round=False
            )
            res[orderpoint.id] += product_uom_qty
        return res
