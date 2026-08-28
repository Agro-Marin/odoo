from odoo import models


class StockRoute(models.Model):
    _inherit = "stock.route"

    def _has_buy_rule(self):
        return any(rule.action == "buy" for rule in self.rule_ids)

    def _is_valid_resupply_route_for_product(self, product):
        if self._has_buy_rule():
            return bool(product.seller_ids)

        return super()._is_valid_resupply_route_for_product(product)
