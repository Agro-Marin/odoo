from odoo import models


class SaleOrderLine(models.Model):
    """Inherit SaleOrderLine"""

    inherit = "sale.order.line"

    # ------------------------------------------------------------
    # ACTION METHODS
    # ------------------------------------------------------------

    def action_add_from_catalog(self):
        order = self.env["sale.order"].browse(self.env.context.get("order_id"))
        return order.action_add_from_catalog()

    # ------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------

    def _get_product_catalog_lines_data(self, **kwargs):
        """Return information about sale order lines in `self`.

        If `self` is empty, this method returns only the default value(s) needed for the product
        catalog. In this case, the quantity that equals 0.

        Otherwise, it returns a quantity and a price based on the product of the SOL(s) and whether
        the product is read-only or not.

        A product is considered read-only if the order is considered read-only (see
        ``SaleOrder._is_readonly`` for more details) or if `self` contains multiple records
        or if it has sale_line_warn == "block".

        Note: This method cannot be called with multiple records that have different products linked.

        :raise odoo.exceptions.ValueError: ``len(self.product_id) != 1``
        :rtype: dict
        :return: A dict with the following structure:
            {
                'quantity': float,
                'price': float,
                'readOnly': bool,
                'warning': String
            }
        """
        if len(self) == 1:
            res = {
                "quantity": self.product_uom_qty,
                "price": self.price_unit,
                "readOnly": (
                    self.order_id._is_readonly()
                    or self.product_id.sale_line_warn == "block"
                    or bool(self.combo_item_id)
                ),
            }
            if self.product_id.sale_line_warn != "no-message" and self.product_id.sale_line_warn_msg:
                res["warning"] = self.product_id.sale_line_warn_msg
            return res
        elif self:
            self.product_id.ensure_one()
            order_line = self[0]
            order = order_line.order_id
            res = {
                "readOnly": True,
                "price": order.pricelist_id._get_product_price(
                    product=order_line.product_id,
                    quantity=1.0,
                    currency=order.currency_id,
                    date=order.date_order,
                    **kwargs,
                ),
                "quantity": sum(
                    self.mapped(
                        lambda line: line.product_uom_id._compute_quantity(
                            qty=line.product_uom_qty,
                            to_unit=line.product_id.uom_id,
                        )
                    )
                ),
            }
            if self.product_id.sale_line_warn != "no-message" and self.product_id.sale_line_warn_msg:
                res["warning"] = self.product_id.sale_line_warn_msg
            return res
        else:
            return {
                "quantity": 0,
                # price will be computed in batch with pricelist utils so not given here
            }
