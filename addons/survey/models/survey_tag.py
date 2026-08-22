from odoo import models


class SurveyTag(models.Model):
    """Freeform tags for classifying and filtering surveys."""

    _name = "survey.tag"
    _description = "Survey Tag"
    # `name` (translated, unique on the source term), `active`, `color` and
    # `code` come from the mixin, which already carried the very uniqueness rule
    # this model was importing on its own. Flat: survey tags do not nest.
    _inherit = ["mixin.tag"]
