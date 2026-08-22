from odoo import api, models


class DecimalPrecision(models.Model):
    _inherit = "decimal.precision"

    @api.model
    def get_precision(self, application):
        stackmap = self.env.cr.cache.get("account_disable_recursion_stack", {})
        if stackmap.get("ignore_discount_precision") and application in (
            "Discount",
            "Product Unit",
        ):
            return 14
        return super().get_precision(application)
