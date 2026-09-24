from odoo import models
from odoo.exceptions import ValidationError


class TaxConfig(models.Model):
    _inherit = "tax.config"

    def write(self, vals):
        if (
            "account_fiscal_country_id" in vals
            and (
                german_configs := self.filtered(
                    lambda config: config.account_fiscal_country_id.code == "DE"
                )
            )
            and self.env["res.country"].browse(vals["account_fiscal_country_id"]).code
            != "DE"
            and self.env["account.move"].search_count(
                [("company_id", "in", german_configs.company_id.ids)], limit=1
            )
        ):
            raise ValidationError(self.env._("You cannot change the fiscal country."))
        return super().write(vals)
