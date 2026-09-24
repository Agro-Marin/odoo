from odoo import api, models
from odoo.exceptions import ValidationError


class TaxConfig(models.Model):
    _inherit = "tax.config"

    @api.constrains("account_price_include")
    def _check_set_account_price_include(self):
        if any(config.company_id.sudo()._existing_accounting() for config in self):
            raise ValidationError(
                self.env._(
                    "Cannot change Price Tax computation method on a company that has already started invoicing."
                )
            )
