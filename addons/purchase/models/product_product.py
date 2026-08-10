from datetime import timedelta

from odoo import _, api, fields, models


class ProductProduct(models.Model):
    _inherit = "product.product"

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    purchased_product_qty = fields.Float(
        string="Purchased",
        digits="Product Unit",
        compute="_compute_purchased_product_qty",
    )
    is_in_purchase_order = fields.Boolean(
        compute="_compute_is_in_purchase_order",
        search="_search_is_in_purchase_order",
    )

    # ------------------------------------------------------------
    # COMPUTE METHODS
    # ------------------------------------------------------------

    def _compute_purchased_product_qty(self):
        self.purchased_product_qty = 0.0
        if not self.env.user.has_group("purchase.group_purchase_user"):
            return
        date_from = fields.Date.today() - timedelta(days=365)
        domain = [
            ("order_id.state", "=", "done"),
            ("product_id", "in", self.ids),
            ("date_confirmed", ">=", date_from),
        ]
        order_lines = self.env["purchase.order.line"]._read_group(
            domain,
            ["product_id"],
            ["product_uom_qty:sum"],
        )
        purchased_data = {product.id: qty for product, qty in order_lines}
        for product in self:
            if not product.id:
                continue
            product.purchased_product_qty = product.uom_id.round(
                purchased_data.get(product.id, 0),
            )

    @api.depends_context("order_id")
    def _compute_is_in_purchase_order(self):
        self._compute_is_in_order("purchase.order.line", "is_in_purchase_order")

    # ------------------------------------------------------------
    # SEARCH METHODS
    # ------------------------------------------------------------

    def _search_is_in_purchase_order(self, operator, value):
        if operator != "in":
            return NotImplemented
        return self._search_is_in_order("purchase.order.line")

    # ------------------------------------------------------------
    # ONCHANGE METHODS
    # ------------------------------------------------------------

    @api.onchange("type")
    def _onchange_type_purchase_warn(self):
        if self._origin and self.purchased_product_qty > 0:
            return {
                "warning": {
                    "title": _("Warning"),
                    "message": _(
                        "You cannot change the product's type because it is already used in purchase orders."
                    ),
                }
            }
        return None

    # ------------------------------------------------------------
    # ACTION METHODS
    # ------------------------------------------------------------

    @api.readonly
    def action_view_po(self):
        action = self.env["ir.actions.actions"]._for_xml_id(
            "purchase.action_purchase_history",
        )
        action["domain"] = [
            ("state", "=", "done"),
            ("product_id", "in", self.ids),
        ]
        action["display_name"] = _("Purchase History for %s", self.display_name)
        return action

    # ------------------------------------------------------------
    # HELPER METHODS
    # ------------------------------------------------------------

    def _get_backend_root_menu_ids(self):
        return super()._get_backend_root_menu_ids() + [
            self.env.ref("purchase.menu_purchase_root").id
        ]

    def _trigger_uom_warning(self):
        res = super()._trigger_uom_warning()
        if res:
            return res
        return self._has_order_lines("purchase.order.line")

    def _update_uom(self, to_uom_id):
        self._update_uom_on_order_lines("purchase.order.line", to_uom_id)
        return super()._update_uom(to_uom_id)
