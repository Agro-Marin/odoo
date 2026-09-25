from odoo import models
from odoo.tools import frozendict


class SurveyQuestion(models.Model):
    _inherit = "survey.question"

    _access_anchors = frozendict(
        {
            "owner_or_unset": models.Anchor(
                "survey_id.restrict_user_ids", kind="owner", shared=True
            ),
        }
    )


class SurveyQuestionAnswer(models.Model):
    _inherit = "survey.question.answer"

    _access_anchors = frozendict(
        {
            "owner_or_unset": models.Anchor(
                "matrix_question_id.survey_id.restrict_user_ids",
                kind="owner",
                shared=True,
            ),
            "question_survey_restrict_user_or_unset": models.Anchor(
                "question_id.survey_id.restrict_user_ids", kind="owner", shared=True
            ),
        }
    )


class SurveyUserInputLine(models.Model):
    _inherit = "survey.user_input.line"

    _access_anchors = frozendict(
        {
            "owner": models.Anchor("survey_id.restrict_user_ids", shared=True),
        }
    )
