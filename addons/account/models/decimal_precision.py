from odoo import api, models

from odoo.addons.account.models.account_move import DISABLE_RECURSION_STACK_CACHE_KEY


class DecimalPrecision(models.Model):
    _inherit = "decimal.precision"

    @api.model
    def get_precision(self, application):
        stackmap = self.env.cr.cache.get(DISABLE_RECURSION_STACK_CACHE_KEY, {})
        if stackmap.get("ignore_discount_precision") and application in (
            "Discount",
            "Product Unit",
        ):
            return 14
        return super().get_precision(application)
