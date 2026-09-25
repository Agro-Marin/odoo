from odoo import fields, models
from odoo.tools import frozendict


class HrApplicantSkill(models.Model):
    _name = "hr.applicant.skill"
    _inherit = "mixin.hr.individual.skill"
    _description = "Skill level for an applicant"
    _order = "skill_type_id, skill_level_id desc"
    _access_anchors = frozendict(
        {
            "applicant_job_interviewer": models.Anchor(
                "applicant_id.job_id.interviewer_ids", kind="owner"
            ),
            "owner": "applicant_id.interviewer_ids",
        }
    )

    applicant_id = fields.Many2one(
        comodel_name="hr.applicant",
        index=True,
        required=True,
        ondelete="cascade",
    )

    def _linked_field_name(self):
        return "applicant_id"
