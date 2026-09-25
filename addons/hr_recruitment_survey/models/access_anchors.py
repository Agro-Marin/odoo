from odoo import models
from odoo.tools import frozendict


class SurveyQuestion(models.Model):
    _inherit = "survey.question"

    _access_anchors = frozendict(
        {
            "survey_hr_job_application_interviewer": models.Anchor(
                "survey_id.hr_job_ids.application_ids.interviewer_ids", kind="owner"
            ),
            "survey_hr_job_interviewer": models.Anchor(
                "survey_id.hr_job_ids.interviewer_ids", kind="owner"
            ),
        }
    )


class SurveyUserInputLine(models.Model):
    _inherit = "survey.user_input.line"

    _access_anchors = frozendict(
        {
            "owner": models.Anchor("survey_id.restrict_user_ids", shared=True),
            "user_input_applicant_interviewer": models.Anchor(
                "user_input_id.applicant_id.interviewer_ids", kind="owner"
            ),
            "user_input_applicant_job_interviewer": models.Anchor(
                "user_input_id.applicant_id.job_id.interviewer_ids", kind="owner"
            ),
        }
    )
