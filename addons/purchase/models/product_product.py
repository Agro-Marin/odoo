from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_round
from odoo.tools.translate import _


class ProductProduct(models.Model):
    """Inherit ProductProduct"""

    _inherit = "product.product"

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    qty_purchased = fields.Float(
        string="Purchased",
        digits="Product Unit",
        compute="_compute_qty_purchased",
    )
    is_in_purchase_order = fields.Boolean(
        compute="_compute_is_in_purchase_order",
        search="_search_is_in_purchase_order",
    )

    # -------------------------------------------------------------------------
    # COMPUTE METHODS
    # -------------------------------------------------------------------------

    def _compute_qty_purchased(self):
        date_from = fields.Date.today() - timedelta(days=365)
        domain = [
            ("state", "=", "purchase"),
            ("product_id", "in", self.ids),
            ("order_id.date_order", ">=", date_from),
        ]
        order_lines = self.env["purchase.order.line"]._read_group(
            domain, ["product_id"], ["product_uom_qty:sum"],
        )
        purchased_data = {product.id: qty for product, qty in order_lines}
        for product in self:
            if not product.id:
                product.qty_purchased = 0.0
                continue

            product.qty_purchased = float_round(
                purchased_data.get(product.id, 0),
                precision_rounding=product.uom_id.rounding,
            )

    @api.depends_context("order_id")
    def _compute_is_in_purchase_order(self):
        order_id = self.env.context.get("order_id")
        if not order_id:
            self.is_in_purchase_order = False
            return

        read_group_data = self.env["purchase.order.line"]._read_group(
            domain=[("order_id", "=", order_id)],
            groupby=["product_id"],
            aggregates=["__count"],
        )
        data = {product.id: count for product, count in read_group_data}
        for product in self:
            product.is_in_purchase_order = bool(data.get(product.id, 0))

    # -------------------------------------------------------------------------
    # SEARCH METHODS
    # -------------------------------------------------------------------------

    def _search_is_in_purchase_order(self, operator, value):
        if operator not in ["=", "!="] or not isinstance(value, bool):
            raise UserError(_("Operation not supported"))

        product_ids = (
            self.env["purchase.order.line"]
            .search(
                [
                    ("order_id", "in", [self.env.context.get("order_id", "")]),
                ]
            )
            .product_id.ids
        )
        return [("id", "in", product_ids)]

    # -------------------------------------------------------------------------
    # ACTIONS
    # -------------------------------------------------------------------------

    def action_view_po(self):
        action = self.env["ir.actions.actions"]._for_xml_id(
            "purchase.action_purchase_history"
        )
        action["domain"] = [
            "&",
            ("state", "=", "purchase"),
            ("product_id", "in", self.ids),
        ]
        action["display_name"] = _("Purchase History for %s", self.display_name)
        return action

    # -------------------------------------------------------------------------
    # HOOKS
    # -------------------------------------------------------------------------
    # TODO lets analyze if both update_uom and check_uom_used can be merged in a single method or
    # a better logic

    def _update_uom(self, to_uom_id):
        for uom, product, po_lines in self.env["purchase.order.line"]._read_group(
            [("product_id", "in", self.ids)],
            ["product_uom_id", "product_id"],
            ["id:recordset"],
        ):
            if uom != product.product_tmpl_id.uom_id:
                raise UserError(
                    _(
                        "As other units of measure (ex : %(problem_uom)s) "
                        "than %(uom)s have already been used for this product, the change of unit of measure can not be done."
                        "If you want to change it, please archive the product and create a new one.",
                        problem_uom=uom.display_name,
                        uom=product.product_tmpl_id.uom_id.display_name,
                    )
                )
            po_lines.product_uom_id = to_uom_id
            po_lines.flush_recordset()

        return super()._update_uom(to_uom_id)

    # -------------------------------------------------------------------------
    # HELPERS
    # -------------------------------------------------------------------------

    def _get_backend_root_menu_ids(self):
        return super()._get_backend_root_menu_ids() + [
            self.env.ref("purchase.menu_purchase_root").id
        ]

    # -------------------------------------------------------------------------
    # VALIDATIONS
    # -------------------------------------------------------------------------

    def _check_uom_used(self):
        res = super()._check_uom_used()
        if res:
            return res
        po_lines = (
            self.env["purchase.order.line"]
            .sudo()
            .search_count([("product_id", "in", self.ids)], limit=1)
        )
        return bool(po_lines)
