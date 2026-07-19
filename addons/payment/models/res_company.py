# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, models


class ResCompany(models.Model):
    _inherit = "res.company"

    @api.model_create_multi
    def create(self, vals_list):
        companies = super().create(vals_list)

        # Duplicate installed providers in the new companies.
        providers_sudo = (
            self.env["payment.provider"]
            .sudo()
            .search(
                [
                    ("company_id", "=", self.env.user.company_id.id),
                    ("module_state", "=", "installed"),
                ]
            )
        )
        # A provider row can hold selection values registered by a module
        # absent from the current registry (e.g. delivery's cash_on_delivery
        # custom_mode during another module's at_install tests): copying it
        # would crash validation. Skip those rows — the partial registry
        # cannot represent them, and the provider they come from is not
        # usable in it either.
        custom_modes = dict(
            self.env["payment.provider"]._fields["custom_mode"].get_description(
                self.env
            )["selection"]
        )
        providers_sudo = providers_sudo.filtered(
            lambda p: not p.custom_mode or p.custom_mode in custom_modes
        )
        for company in companies:
            if company.parent_id:  # The company is a branch.
                continue  # Only consider top-level companies for provider duplication.

            for provider_sudo in providers_sudo:
                provider_sudo.copy({"company_id": company.id})

        return companies
