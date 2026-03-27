from random import randint

from odoo import fields, models


class SurveyTag(models.Model):
    """Freeform tags for classifying and filtering surveys."""

    _name = "survey.tag"
    _description = "Survey Tag"
    _order = "name"

    def _get_default_color(self) -> int:
        return randint(1, 11)

    name = fields.Char("Tag Name", required=True, translate=True)
    color = fields.Integer("Color", default=_get_default_color)

    _name_uniq = models.Constraint(
        "unique (name)",
        "Tag name already exists!",
    )
