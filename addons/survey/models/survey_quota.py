from typing import Self

from odoo import api, fields, models


class SurveyQuota(models.Model):
    """Response quota for a specific answer option within a survey.

    When the number of completed responses selecting a particular answer reaches
    the configured limit, new respondents who select that answer are shown a
    "quota full" message and their response is not recorded for that question.
    """

    _name = "survey.quota"
    _description = "Survey Quota"
    _order = "survey_id, question_id, id"

    survey_id = fields.Many2one(
        "survey.survey",
        string="Survey",
        required=True,
        ondelete="cascade",
        index="btree_not_null",
    )
    question_id = fields.Many2one(
        "survey.question",
        string="Question",
        required=True,
        ondelete="cascade",
        domain="[('survey_id', '=', survey_id), ('question_type', 'in', ['simple_choice', 'multiple_choice'])]",
    )
    answer_id = fields.Many2one(
        "survey.question.answer",
        string="Answer",
        required=True,
        ondelete="cascade",
        domain="[('question_id', '=', question_id)]",
    )
    limit = fields.Integer(
        "Quota Limit",
        required=True,
        default=100,
        help="Maximum number of completed responses that can select this answer.",
    )
    current_count = fields.Integer(
        "Current Count",
        compute="_compute_current_count",
    )
    is_full = fields.Boolean(
        "Quota Full",
        compute="_compute_current_count",
    )
    active = fields.Boolean(default=True)

    _limit_positive = models.Constraint(
        'CHECK ("limit" > 0)',
        "Quota limit must be positive!",
    )

    @api.depends("survey_id", "answer_id", "limit")
    def _compute_current_count(self) -> None:
        """Count completed responses that selected this answer."""
        for quota in self:
            count = self.env["survey.user_input.line"].search_count(
                [
                    ("survey_id", "=", quota.survey_id.id),
                    ("suggested_answer_id", "=", quota.answer_id.id),
                    ("user_input_id.state", "=", "done"),
                    ("user_input_id.test_entry", "=", False),
                ]
            )
            quota.current_count = count
            quota.is_full = count >= quota.limit

    def _check_quota(self, answer_ids: list[int]) -> Self:
        """Check if any of the given answer IDs would exceed their quota.

        :param answer_ids: list of ``survey.question.answer`` IDs being submitted
        :returns: recordset of quota records that are already full
        """
        full_quotas = self.env["survey.quota"]
        for quota in self.filtered("active"):
            if quota.answer_id.id in answer_ids and quota.is_full:
                full_quotas |= quota
        return full_quotas
