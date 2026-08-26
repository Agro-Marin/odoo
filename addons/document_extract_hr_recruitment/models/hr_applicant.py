from __future__ import annotations

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class HrApplicant(models.Model):
    _name = "hr.applicant"
    _inherit = ["hr.applicant", "mixin.document.extract"]

    _extract_document_type = "resume"

    _extract_target = {
        "full_name": "partner_name",
        "email": "email_from",
        "phone": "partner_phone",
    }

    extract_can_be_read = fields.Boolean(compute="_compute_extract_can_be_read")

    @api.depends("stage_id", "job_id", "extract_state")
    def _compute_extract_can_be_read(self) -> None:
        first_stage_by_job = {}
        for applicant in self:
            job_id = applicant.job_id.id
            if job_id not in first_stage_by_job:
                first_stage_by_job[job_id] = applicant._get_first_recruitment_stage()
            applicant.extract_can_be_read = applicant.stage_id == first_stage_by_job[
                job_id
            ] and applicant.extract_state in ("none", "failed", "partial")

    def _get_first_recruitment_stage(self):
        self.ensure_one()
        return self.env["hr.recruitment.stage"].search(
            [
                "|",
                ("job_ids", "=", False),
                ("job_ids", "=", self.job_id.id),
                ("fold", "=", False),
            ],
            order="sequence asc",
            limit=1,
        )

    def action_extract_document(self):
        self.ensure_one()
        if not self.extract_can_be_read:
            raise UserError(
                _(
                    "A CV is read while the applicant is still in the first stage. "
                    "Past it somebody has been through this record, and a reading "
                    "would be correcting a person from a document they have read."
                )
            )
        result = self._extract_document()
        if result is None:
            return False
        if result.satisfied:
            message = _("The CV was read in full.")
        else:
            message = _(
                "The CV was read in part. Still missing: %(fields)s",
                fields=", ".join(result.missing) or _("nothing required"),
            )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {"message": message, "type": "info", "sticky": False},
        }
