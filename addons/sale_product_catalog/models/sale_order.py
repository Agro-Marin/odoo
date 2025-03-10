from collections import defaultdict

from odoo import models
from odoo.http import request
from odoo.osv import expression


class SaleOrder(models.Model):
    """Inherit SaleOrder"""

    _inherit = ["sale.order", "product.catalog.mixin"]

    # ------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------

    def _default_order_line_values(self, child_field=False):
        default_data = super()._default_order_line_values(child_field)
        new_default_data = self.env["sale.order.line"]._get_product_catalog_lines_data()
        return {**default_data, **new_default_data}

    def _get_action_add_from_catalog_extra_context(self):
        return {
            **super()._get_action_add_from_catalog_extra_context(),
            "product_catalog_currency_id": self.currency_id.id,
            "product_catalog_digits": self.line_ids._fields["price_unit"].get_digits(self.env),
        }

    def _get_product_catalog_domain(self):
        return expression.AND([super()._get_product_catalog_domain(), [("sale_ok", "=", True)]])

    def _get_product_catalog_order_data(self, products, **kwargs):
        pricelist = self.pricelist_id._get_products_price(
            quantity=1.0,
            products=products,
            currency=self.currency_id,
            date=self.date_order,
            **kwargs,
        )
        res = super()._get_product_catalog_order_data(products, **kwargs)
        for product in products:
            res[product.id]["price"] = pricelist.get(product.id)
            if product.sale_line_warn != "no-message" and product.sale_line_warn_msg:
                res[product.id]["warning"] = product.sale_line_warn_msg
            if product.sale_line_warn == "block":
                res[product.id]["readOnly"] = True
        return res

    def _get_product_catalog_record_lines(self, product_ids, **kwargs):
        grouped_lines = defaultdict(lambda: self.env["sale.order.line"])
        for line in self.line_ids:
            if line.display_type or line.product_id.id not in product_ids:
                continue
            grouped_lines[line.product_id] |= line
        return grouped_lines

    # ------------------------------------------------------------
    # BUSINESS LOGIC METHODS
    # ------------------------------------------------------------

    def _discard_tracking(self):
        """Discard tracking only for catalog updates"""
        self.ensure_one()
        return self.state == "draft" and request and request.env.context.get("catalog_skip_tracking")

    def _track_finalize(self):
        """Override of `mail` to prevent logging changes when the SO is in 'draft' state and catalog updates mode"""
        if (
            len(self) == 1
            # The method _track_finalize is sometimes called too early or too late and it
            # might cause a desynchronization with the cache, thus this condition is needed.
            and self.env.cache.contains(self, self._fields["state"])
            and self._discard_tracking()
        ):
            self.env.cr.precommit.data.pop(f"mail.tracking.{self._name}", {})
            self.env.flush_all()
            return
        return super()._track_finalize()

    def _update_order_line_info(self, product_id, quantity, **kwargs):
        """Update sale order line information for a given product or create a
        new one if none exists yet.
        :param int product_id: The product, as a `product.product` id.
        :return: The unit price of the product, based on the pricelist of the
                 sale order and the quantity selected.
        :rtype: float
        """
        request.update_context(catalog_skip_tracking=True)
        sol = self.line_ids.filtered(lambda line: line.product_id.id == product_id)
        if sol:
            if quantity != 0:
                sol.product_uom_qty = quantity
            elif self.state in ["draft", "sent"]:
                price_unit = self.pricelist_id._get_product_price(
                    product=sol.product_id,
                    quantity=1.0,
                    currency=self.currency_id,
                    date=self.date_order,
                    **kwargs,
                )
                sol.unlink()
                return price_unit
            else:
                sol.product_uom_qty = 0
        elif quantity > 0:
            sol = self.env["sale.order.line"].create(
                {
                    "order_id": self.id,
                    "product_id": product_id,
                    "product_uom_qty": quantity,
                    "sequence": (
                        (self.line_ids and self.line_ids[-1].sequence + 1) or 10
                    ),  # put it at the end of the order
                }
            )
        return sol.price_unit * (1 - (sol.discount or 0.0) / 100.0)
