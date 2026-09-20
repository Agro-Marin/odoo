from odoo import models
from odoo.http import request

from odoo.addons.website_sale_collect import utils


class ProductTemplate(models.Model):
    _inherit = "product.template"

    def _get_additionnal_combination_info(
        self, product_or_template, quantity, uom, date, website
    ):
        res = super()._get_additionnal_combination_info(
            product_or_template, quantity, uom, date, website
        )
        if (
            bool(website.sudo().in_store_dm_id)
            and product_or_template.is_product_variant
            and product_or_template.is_storable
        ):
            res["show_click_and_collect_availability"] = True

            available_delivery_methods_sudo = (
                self.env["delivery.carrier"]
                .sudo()
                .search(
                    [
                        "|",
                        ("website_id", "=", website.id),
                        ("website_id", "=", False),
                        ("website_published", "=", True),
                        ("delivery_type", "!=", "in_store"),
                    ]
                )
            )
            if available_delivery_methods_sudo:
                res["delivery_stock_data"] = utils.format_product_stock_values(
                    product_or_template.sudo(), wh_id=website.warehouse_id.id
                )
            else:
                res["delivery_stock_data"] = {}

            order_sudo = request.cart
            if (
                order_sudo
                and order_sudo.carrier_id.delivery_type == "in_store"
                and order_sudo.pickup_location_data
            ):
                res["in_store_stock_data"] = utils.format_product_stock_values(
                    product_or_template.sudo(),
                    wh_id=order_sudo.pickup_location_data["id"],
                )
            else:
                res["in_store_stock_data"] = utils.format_product_stock_values(
                    product_or_template.sudo(),
                    qty_free=website.sudo()._get_max_in_store_product_available_qty(
                        product_or_template.sudo()
                    ),
                )
        return res
