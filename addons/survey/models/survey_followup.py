"""Automated follow-up email rules for survey completion.

Each rule defines a condition (score range, specific answer, or always) and
a mail template to send when the condition is met after survey completion.
"""

import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class SurveyFollowupRule(models.Model):
    """Automated email rule triggered after survey completion.

    Rules are evaluated in sequence order. Multiple rules can fire for the
    same response if their conditions are all met (they are independent).
    """

    _name = "survey.followup.rule"
    _description = "Survey Follow-up Rule"
    _order = "sequence, id"

    survey_id = fields.Many2one(
        "survey.survey",
        string="Survey",
        required=True,
        ondelete="cascade",
        index="btree_not_null",
    )
    sequence = fields.Integer("Sequence", default=10)
    name = fields.Char("Rule Name", required=True)
    active = fields.Boolean("Active", default=True)

    # -- condition
    condition_type = fields.Selection(
        [
            ("always", "Always (on every completion)"),
            ("score_range", "Score in range"),
            ("passed", "Passed certification"),
            ("failed", "Failed certification"),
        ],
        string="Condition",
        required=True,
        default="always",
    )
    score_min = fields.Float(
        "Min Score (%)",
        help="Minimum scoring_percentage to trigger (inclusive).",
    )
    score_max = fields.Float(
        "Max Score (%)",
        default=100,
        help="Maximum scoring_percentage to trigger (inclusive).",
    )

    # -- action
    mail_template_id = fields.Many2one(
        "mail.template",
        string="Email Template",
        required=True,
        domain="[('model', '=', 'survey.user_input')]",
        help="Email template to send. Available variables: object (survey.user_input).",
    )

    def _evaluate(self, user_input):
        """Check if this rule's condition is met for the given user_input.

        :param user_input: survey.user_input record (single)
        :returns: True if condition is met
        """
        self.ensure_one()
        if self.condition_type == "always":
            return True
        elif self.condition_type == "score_range":
            return self.score_min <= user_input.scoring_percentage <= self.score_max
        elif self.condition_type == "passed":
            return user_input.scoring_success
        elif self.condition_type == "failed":
            return not user_input.scoring_success
        return False

    def _execute(self, user_input):
        """Send the follow-up email for this rule if its condition is met."""
        self.ensure_one()
        if not self._evaluate(user_input):
            return
        try:
            self.mail_template_id.send_mail(
                user_input.id, force_send=False,
            )
            _logger.info(
                "Follow-up rule '%s' fired for input %s",
                self.name, user_input.id,
            )
        except Exception:
            _logger.warning(
                "Follow-up rule '%s' failed for input %s",
                self.name, user_input.id,
                exc_info=True,
            )
