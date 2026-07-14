from odoo import _
from odoo.exceptions import UserError
from odoo.http import Controller, request, route


class ProductCatalogController(Controller):
    @staticmethod
    def _get_order(res_model, order_id):
        """Browse the order targeted by a catalog route, safely.

        `res_model`/`order_id` are client-provided: only models implementing
        `product.catalog.mixin` are valid targets, and the record must exist
        (record rules are enforced by the ORM on the later read/write).
        """
        env = request.env
        if res_model not in env.registry or not isinstance(
            env[res_model], env.registry["product.catalog.mixin"]
        ):
            raise UserError(_("The product catalog cannot be used on this model."))
        order = env[res_model].browse(int(order_id)).exists()
        if not order:
            raise UserError(_("The requested record does not exist."))
        return order

    @route(
        "/product/catalog/order_lines_info", auth="user", type="jsonrpc", readonly=True
    )
    def product_catalog_get_order_lines_info(
        self, res_model, order_id, product_ids, **kwargs
    ):
        """Returns products information to be shown in the catalog.

        :param string res_model: The order model.
        :param int order_id: The order id.
        :param list product_ids: The products currently displayed in the product catalog, as a list
                                 of `product.product` ids.
        :rtype: dict
        :return: A dict with the following structure:
            {
                product.id: {
                    'productId': int
                    'quantity': float (optional)
                    'price': float
                    'uomDisplayName': string
                    'code': string (optional)
                    'readOnly': bool (optional)
                }
            }
        """
        order = self._get_order(res_model, order_id)
        return order.with_company(
            order.company_id
        )._get_product_catalog_order_line_info(
            product_ids,
            **kwargs,
        )

    @route("/product/catalog/update_order_line_info", auth="user", type="jsonrpc")
    def product_catalog_update_order_line_info(
        self, res_model, order_id, product_id, quantity=0, **kwargs
    ):
        """Update order line information on a given order for a given product.

        :param string res_model: The order model.
        :param int order_id: The order id.
        :param int product_id: The product, as a `product.product` id.
        :return: The unit price price of the product, based on the pricelist of the order and
                 the quantity selected.
        :rtype: float
        """
        order = self._get_order(res_model, order_id)
        # The UI disables edition based on `_is_readonly()`; enforce the same
        # rule here so direct RPC calls cannot edit locked/done records.
        if order._is_readonly():
            raise UserError(_("You cannot edit the products of a read-only record."))
        return order.with_company(order.company_id)._update_order_line_info(
            product_id,
            quantity,
            **kwargs,
        )
