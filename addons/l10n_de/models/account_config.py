from odoo import api, models


class AccountConfig(models.Model):
    _inherit = "account.config"

    @api.depends("company_id.country_code")
    def _compute_force_restrictive_audit_trail(self):
        super()._compute_force_restrictive_audit_trail()
        for config in self:
            config.force_restrictive_audit_trail |= (
                config.company_id.country_code == "DE"
            )
