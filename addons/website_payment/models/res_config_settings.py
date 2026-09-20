from odoo import api, models
from odoo.fields import Domain


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    @api.depends("company_id", "website_id")
    def _compute_active_provider_id(self):
        return super()._compute_active_provider_id()

    @api.depends("company_id", "website_id")
    def _compute_has_enabled_provider(self):
        return super()._compute_has_enabled_provider()

    def _get_domain_active_providers(self, *args, **kwargs):
        self.check_singleton()
        return Domain.AND(
            [
                super()._get_domain_active_providers(*args, **kwargs),
                [
                    "|",
                    ("website_id", "=", False),
                    ("website_id", "=", self.website_id.id),
                ],
            ]
        )

    def action_w_payment_start_payment_onboarding(self):
        menu = self.env.ref(
            "website.menu_website_website_settings", raise_if_not_found=False
        )
        return self._start_payment_onboarding(menu and menu.id)
