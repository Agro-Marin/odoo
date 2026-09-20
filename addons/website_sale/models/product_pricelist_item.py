from odoo import models


class ProductPricelistItem(models.Model):
    _inherit = "product.pricelist.item"

    def _show_discount_on_shop(self):
        if not self:
            return False

        self.check_singleton()

        return self.compute_price == "percentage" or (
            self.compute_price == "formula"
            and self.price_discount
            and self.base in ("list_price", "pricelist")
        )
