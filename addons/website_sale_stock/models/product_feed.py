from odoo import models


class ProductFeed(models.Model):
    _inherit = "product.feed"

    def _prepare_gmc_stock_info(self, product):
        stock_info = super()._prepare_gmc_stock_info(product)
        if product._is_sold_out():
            stock_info["availability"] = "out_of_stock"
        return stock_info
