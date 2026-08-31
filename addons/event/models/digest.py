from odoo import _, fields, models
from odoo.exceptions import AccessError


class DigestDigest(models.Model):
    _inherit = "digest.digest"

    kpi_nbr_of_registrations = fields.Boolean("Registrations")
    kpi_nbr_of_registrations_value = fields.Integer(
        compute="_compute_kpi_nbr_of_registrations_value"
    )

    def _compute_kpi_nbr_of_registrations_value(self):
        if not self.env.user.has_group("event.group_event_manager"):
            raise AccessError(
                _("Do not have access, skip this data for user's digest email")
            )

        self._calculate_company_based_kpi(
            "event.registration", "kpi_nbr_of_registrations_value"
        )

    def _get_kpi_actions(self, company, user):
        res = super()._get_kpi_actions(company, user)
        res["kpi_nbr_of_registrations"] = "event.action_registration"
        return res
