from odoo import api, models
from odoo.fields import Domain


class Company(models.Model):

    _inherit = "res.company"

    def _reset_default_documents_folder_id(
        self,
        toggle_field_name: str,
        folder_field_name: str,
        default_folder_id: models.Model,
    ) -> None:
        if not default_folder_id or not default_folder_id.active:
            return
        bridge_enabling_companies = self.filtered(toggle_field_name).filtered(
            lambda c: not c[folder_field_name]
        )
        bridge_enabling_companies[folder_field_name] = default_folder_id

    @api.model
    def _get_used_folder_ids_domain(self, folder_ids: list[int]) -> Domain:
        return Domain.FALSE
