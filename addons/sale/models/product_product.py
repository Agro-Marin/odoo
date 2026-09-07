from odoo import _, api, fields, models


class ProductProduct(models.Model):
    _inherit = "product.product"

    sales_count = fields.Float(
        string="Sold",
        digits="Product Unit",
        compute="_compute_sales_count",
    )
    is_in_sale_order = fields.Boolean(
        compute="_compute_is_in_sale_order",
        search="_search_is_in_sale_order",
    )
    previously_bought_by_customer = fields.Boolean(
        string="Previously Bought",
        search="_search_previously_bought_by_customer",
    )

    def _compute_sales_count(self):
        self._compute_ordered_qty(
            "sales_count",
            "sale.report",
            "sales_team.group_sale_salesman",
            "date_order",
            [("state", "in", self.env["sale.report"]._get_done_states())],
        )

    @api.depends_context("order_id")
    def _compute_is_in_sale_order(self):
        self._compute_is_in_order("sale.order.line", "is_in_sale_order")

    def _search_is_in_sale_order(self, operator, value):
        if operator != "in":
            return NotImplemented
        return self._search_is_in_order("sale.order.line")

    def _search_previously_bought_by_customer(self, operator, value):
        """The products this order's customer has already been sold.

        The customer comes from the `order_id` the catalog action already puts
        in the context (`product/models/mixin_product_catalog.py`), so nothing
        outside `sale` has to carry a second key for it. With no order there is
        no customer, and a filter with no customer must match nothing rather
        than hand back the whole catalog.
        """
        if operator != "in":
            return NotImplemented
        order_id = self.env.context.get("order_id")
        if not order_id:
            return [("id", "in", [])]
        partner = self.env["sale.order"].browse(order_id).partner_id
        product_ids = (
            self.env["sale.order.line"]
            .search_fetch(
                [("partner_id", "=", partner.id), ("state", "=", "done")],
                ["product_id"],
            )
            .product_id.ids
        )
        return [("id", "in", product_ids)]

    @api.onchange("type")
    def _onchange_type(self):
        if self._origin and self.sales_count > 0:
            return {
                "warning": {
                    "title": _("Warning"),
                    "message": _(
                        "You cannot change the product's type because it is already used in sales orders."
                    ),
                }
            }
        return None

    @api.readonly
    def action_view_sales(self):
        # The line-level history, not the `sale.report` pivot the button used
        # to open: purchase's twin has always answered "what did each document
        # charge", and an aggregate view cannot. The pivot is still one click
        # away -- it is the second view of this action.
        action = self.env["ir.actions.actions"]._get_action_dict_by_xml_id(
            "sale.action_sale_history",
        )
        action["domain"] = [
            ("state", "=", "done"),
            ("product_id", "in", self.ids),
        ]
        action["display_name"] = _("Sales History for %s", self.display_name)
        return action

    def _filter_to_unlink(self):
        domain = [("product_id", "in", self.ids)]
        lines = self.env["sale.order.line"]._read_group(domain, ["product_id"])
        linked_product_ids = [product.id for [product] in lines]
        return super(
            ProductProduct, self - self.browse(linked_product_ids)
        )._filter_to_unlink()

    def _get_backend_root_menu_ids(self):
        return super()._get_backend_root_menu_ids() + [
            self.env.ref("sale.sale_menu_root").id
        ]

    def _get_invoice_policy(self):
        return self.invoice_policy

    def _trigger_uom_warning(self):
        res = super()._trigger_uom_warning()
        if res:
            return res
        return self._has_order_lines("sale.order.line")

    def _update_uom(self, to_uom_id):
        self._update_uom_on_order_lines("sale.order.line", to_uom_id)
        return super()._update_uom(to_uom_id)
