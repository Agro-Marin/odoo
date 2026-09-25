from odoo import fields, models
from odoo.tools import frozendict


class SurveySurvey(models.Model):
    _inherit = "survey.survey"
    _access_anchors = frozendict(
        {
            "slide_channel_user": models.Anchor(
                "slide_ids.channel_id.user_id", kind="owner"
            ),
            "user": models.Anchor("user_id", kind="owner"),
        }
    )

    slide_ids = fields.One2many(
        comodel_name="slide.slide",
        inverse_name="survey_id",
        string="Slides",
        help="The slides this survey is linked to through the eLearning application",
    )
