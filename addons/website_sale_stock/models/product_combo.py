from odoo import models


class ProductCombo(models.Model):
    _inherit = "product.combo"

    def _get_max_quantity(self, website, sale_order, **kwargs):
        self.check_singleton()
        max_quantities = [
            item.product_id._get_max_quantity(website, sale_order, **kwargs)
            for item in self.combo_item_ids
        ]
        return max(max_quantities) if (None not in max_quantities) else None
