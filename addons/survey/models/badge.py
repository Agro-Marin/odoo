from odoo import api, fields, models


class GamificationBadge(models.Model):
    """Extend gamification badge with survey certification link."""

    _inherit = "gamification.badge"

    survey_ids = fields.One2many(
        "survey.survey", "certification_badge_id", "Survey Ids"
    )
    survey_id = fields.Many2one(
        "survey.survey", "Survey", compute="_compute_survey_id", store=True
    )

    @api.depends("survey_ids.certification_badge_id")
    def _compute_survey_id(self) -> None:
        for badge in self:
            badge.survey_id = badge.survey_ids[0] if badge.survey_ids else None
