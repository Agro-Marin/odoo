from odoo import fields, models


class SurveySurvey(models.Model):
    _inherit = "survey.survey"

    # The inverse of slide.slide.survey_id, which this module declares. It used
    # to live in website_slides_survey while the many2one lived here, so the
    # record rules that scope an eLearning officer to their own courses could
    # not be expressed in the module that grants them the access.
    slide_ids = fields.One2many(
        "slide.slide",
        "survey_id",
        string="Slides",
        help="The slides this survey is linked to through the eLearning application",
    )
