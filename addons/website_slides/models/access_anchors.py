from odoo import models
from odoo.tools import frozendict


class SurveyQuestion(models.Model):
    _inherit = "survey.question"

    _access_anchors = frozendict(
        {
            "survey_slide_channel_user": models.Anchor(
                "survey_id.slide_ids.channel_id.user_id", kind="owner"
            ),
            "survey_user": models.Anchor("survey_id.user_id", kind="owner"),
        }
    )


class SurveyQuestionAnswer(models.Model):
    _inherit = "survey.question.answer"

    _access_anchors = frozendict(
        {
            "question_survey_slide_channel_user": models.Anchor(
                "question_id.survey_id.slide_ids.channel_id.user_id", kind="owner"
            ),
            "question_survey_user": models.Anchor(
                "question_id.survey_id.user_id", kind="owner"
            ),
        }
    )
