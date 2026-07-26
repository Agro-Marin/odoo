from odoo import api, models
from odoo.fields import Domain


class Company(models.Model):
    """Company model extended with documents bridge folder helpers."""

    _inherit = "res.company"

    def _reset_default_documents_folder_id(
        self,
        toggle_field_name: str,
        folder_field_name: str,
        default_folder_id: models.Model,
    ) -> None:
        """Reset the company folder when a bridge is (re-)enabled.

        To be used in an onchange (see bridges), allowing to set "default_folder_id"
        - as default on creation
        - as new value if the bridge is (re-)enabled (and the previous folder was unlinked).
        """
        if not default_folder_id or not default_folder_id.active:
            return
        bridge_enabling_companies = self.filtered(toggle_field_name).filtered(
            lambda c: not c[folder_field_name]
        )
        bridge_enabling_companies[folder_field_name] = default_folder_id

    @api.model
    def _get_used_folder_ids_domain(self, folder_ids: list[int]) -> Domain:
        """Return the domain for folders being used by a company for a documents bridge."""
        return Domain.FALSE
