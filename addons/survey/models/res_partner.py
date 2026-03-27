from typing import Any

from odoo import api, fields, models


class ResPartner(models.Model):
    """Extend res.partner with certification statistics."""

    _inherit = "res.partner"

    certifications_count = fields.Integer(
        "Certifications Count", compute="_compute_certifications_count"
    )
    certifications_company_count = fields.Integer(
        "Company Certifications Count", compute="_compute_certifications_company_count"
    )

    @api.depends("is_company")
    def _compute_certifications_count(self) -> None:
        read_group_res = (
            self.env["survey.user_input"]
            .sudo()
            ._read_group(
                [("partner_id", "in", self.ids), ("scoring_success", "=", True)],
                ["partner_id"],
                ["__count"],
            )
        )
        data = {partner.id: count for partner, count in read_group_res}
        for partner in self:
            partner.certifications_count = data.get(partner.id, 0)

    @api.depends("is_company", "child_ids.certifications_count")
    def _compute_certifications_company_count(self) -> None:
        for partner in self:
            partner.certifications_company_count = sum(
                child.certifications_count for child in partner.child_ids
            )

    def action_view_certifications(self) -> dict[str, Any]:
        """Open the list of successful certification attempts for this partner (and children)."""
        action = self.env["ir.actions.actions"]._for_xml_id(
            "survey.res_partner_action_certifications"
        )
        action["view_mode"] = "list"
        action["domain"] = [
            ("scoring_success", "=", True),
            "|",
            ("partner_id", "in", self.ids),
            ("partner_id", "in", self.child_ids.ids),
        ]

        return action
