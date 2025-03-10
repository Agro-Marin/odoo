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

    qty_sold = fields.Float(
        string="Sold",
        digits="Product Unit",
        compute="_compute_qty_sold",
    )

    # ------------------------------------------------------------
    # COMPUTE METHODS
    # ------------------------------------------------------------

    def _compute_qty_sold(self):
        r = {}
        self.qty_sold = 0
        if not self.env.user.has_group("sales_team.group_sale_salesman"):
            return r

        date_from = fields.Date.today() - timedelta(days=365)
        done_states = self.env["sale.report"]._get_done_states()
        domain = [
            ("state", "in", done_states),
            ("product_id", "in", self.ids),
            ("date_order", ">=", date_from),
        ]
        for product, product_uom_qty in self.env["sale.report"]._read_group(
            domain, ["product_id"], ["product_uom_qty:sum"],
        ):
            r[product.id] = product_uom_qty
        for product in self:
            if not product.id:
                product.qty_sold = 0.0
                continue

            product.qty_sold = float_round(
                r.get(product.id, 0), precision_rounding=product.uom_id.rounding
            )
        return r

    # ------------------------------------------------------------
    # ONCHANGE METHODS
    # ------------------------------------------------------------

    @api.onchange("type")
    def _onchange_type(self):
        if self._origin and self.qty_sold > 0:
            return {
                "warning": {
                    "title": _("Warning"),
                    "message": _(
                        "You cannot change the product's type because it is already used in sales orders."
                    ),
                }
            }

    # ------------------------------------------------------------
    # SEARCH METHODS
    # ------------------------------------------------------------

    def _search_product_is_in_sale_order(self, operator, value):
        if operator not in ["=", "!="] or not isinstance(value, bool):
            raise UserError(_("Operation not supported"))

        product_ids = (
            self.env["sale.order.line"]
            .search(
                [
                    ("order_id", "in", [self.env.context.get("order_id", "")]),
                ]
            )
            .product_id.ids
        )
        return [("id", "in", product_ids)]

    # ------------------------------------------------------------
    # ACTIONS
    # ------------------------------------------------------------

    @api.readonly
    def action_view_sales(self):
        action = self.env["ir.actions.actions"]._for_xml_id(
            "sale.report_all_channels_sales_action"
        )
        action["domain"] = [("product_id", "in", self.ids)]
        action["context"] = {
            "pivot_measures": ["product_uom_qty"],
            "active_id": self._context.get("active_id"),
            "search_default_Sales": 1,
            "active_model": "sale.report",
            "search_default_filter_order_date_365": 1,
        }
        return action

    # ------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------

    def _update_uom(self, to_uom_id):
        for uom, product, so_lines in self.env["sale.order.line"]._read_group(
            [("product_id", "in", self.ids)],
            ["product_uom_id", "product_id"],
            ["id:recordset"],
        ):
            if so_lines.product_uom_id != product.product_tmpl_id.uom_id:
                raise UserError(
                    _(
                        "As other units of measure (ex : %(problem_uom)s) "
                        "than %(uom)s have already been used for this product, the change of unit of measure can not be done."
                        "If you want to change it, please archive the product and create a new one.",
                        problem_uom=uom.display_name,
                        uom=product.product_tmpl_id.uom_id.display_name,
                    )
                )

            so_lines.product_uom_id = to_uom_id
        return super()._update_uom(to_uom_id)

    def _get_backend_root_menu_ids(self):
        return super()._get_backend_root_menu_ids() + [
            self.env.ref("sale.sale_menu_root").id
        ]

    def _get_invoice_policy(self):
        return self.invoice_policy

    def _filter_to_unlink(self):
        domain = [("product_id", "in", self.ids)]
        lines = self.env["sale.order.line"]._read_group(domain, ["product_id"])
        linked_product_ids = [product.id for [product] in lines]
        return super(
            ProductProduct, self - self.browse(linked_product_ids)
        )._filter_to_unlink()

    # ------------------------------------------------------------
    # VALIDATIONS
    # ------------------------------------------------------------

    def _check_uom_used(self):
        res = super()._check_uom_used()
        if res:
            return res

        so_lines = (
            self.env["sale.order.line"]
            .sudo()
            .search_count([("product_id", "in", self.ids)], limit=1)
        )
        return bool(so_lines)
