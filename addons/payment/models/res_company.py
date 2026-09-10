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
        # A provider row exists in the database whether or not the module that
        # declares its `code` (and, for payment_custom, its `custom_mode`) is in
        # the registry right now: an at_install test of a module loaded before
        # payment_custom sees the installed "Wire Transfer" row through a
        # registry whose `code` selection has no 'custom', and copying it would
        # fail validation. The provider is exactly as unusable in that registry
        # as it is invalid, so the copy follows the registry and not the table.
        loaded = self.env.registry.loaded_modules
        providers_sudo = providers_sudo.filtered(lambda p: p.module_id.name in loaded)
        for company in companies:
            if company.parent_id:  # The company is a branch.
                continue  # Only consider top-level companies for provider duplication.

            for provider_sudo in providers_sudo:
                provider_sudo.copy({"company_id": company.id})

        return companies
