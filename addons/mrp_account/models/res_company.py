from odoo import models


class ResCompany(models.Model):
    _inherit = "res.company"

    def _get_domain_valuation_product(self):
        return super()._get_domain_valuation_product() + [("is_kit", "=", False)]
