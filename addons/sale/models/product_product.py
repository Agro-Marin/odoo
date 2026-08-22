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
        action = self.env["ir.actions.actions"]._get_action_dict_by_xml_id(
            "sale.action_sale_report_all_channels_sales",
        )
        action["domain"] = [
            ("state", "=", "done"),
            ("product_id", "in", self.ids),
        ]
        action["context"] = {
            "pivot_measures": ["product_uom_qty"],
            "active_id": self.env.context.get("active_id"),
            "search_default_Sales": 1,
            "active_model": "sale.report",
            "search_default_filter_order_date": 1,
        }
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
