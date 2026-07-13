"""Benefits realization tracking.

Evidence basis: PMI BRM — projects routinely succeed on the iron triangle
while failing to deliver business value. Named benefits ownership
dramatically outperforms assumption-based approaches (ScienceDirect 2014).
"""

import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class ProjectBenefit(models.Model):
    """An expected business benefit tied to a project, with target and actual measurement."""

    _name = "project.benefit"
    _description = "Project Benefit"
    _order = "sequence, id"
    _inherit = ["mail.thread"]

    name = fields.Char("Benefit", required=True, tracking=True)
    sequence = fields.Integer(default=10)
    project_id = fields.Many2one(
        "project.project",
        required=True,
        ondelete="cascade",
        index=True,
    )
    description = fields.Html(
        "How This Benefit Will Be Realized",
        help="Describe the mechanism by which this benefit is expected to materialize.",
    )
    measurement_method = fields.Text(
        "Measurement Method",
        help="Specific, quantified method for measuring this benefit.",
    )
    target_value = fields.Float("Target Value")
    target_unit = fields.Char(
        "Unit",
        help="Unit of measurement (e.g. %, $, hours, NPS score).",
    )
    actual_value = fields.Float("Actual Value")
    achievement_pct = fields.Float(
        "Achievement %",
        compute="_compute_achievement_pct",
        store=True,
        help="Actual / Target as a percentage.",
        export_string_translation=False,
    )
    accountable_id = fields.Many2one(
        "res.users",
        string="Accountable Owner",
        tracking=True,
        help="Business owner responsible for realizing and measuring this benefit.",
    )
    review_date = fields.Date(
        "Next Review Date",
        help="When this benefit should next be reviewed for progress.",
    )
    state = fields.Selection(
        [
            ("expected", "Expected"),
            ("tracking", "Tracking"),
            ("achieved", "Achieved"),
            ("partially", "Partially Achieved"),
            ("not_achieved", "Not Achieved"),
        ],
        default="expected",
        required=True,
        tracking=True,
    )
    notes = fields.Html("Review Notes")

    @api.model
    def _cron_check_review_dates(self) -> None:
        """Create activities for benefits whose review date has arrived.

        Called daily by ir.cron. Searches for benefits in 'expected' or
        'tracking' state where review_date <= today and the accountable
        owner is set, then schedules a mail.activity reminder.
        """
        today = fields.Date.context_today(self)
        benefits = self.search(
            [
                ("review_date", "<=", today),
                ("state", "in", ("expected", "tracking")),
                ("accountable_id", "!=", False),
            ]
        )
        if not benefits:
            return

        activity_type = self.env.ref(
            "mail.mail_activity_data_todo", raise_if_not_found=False
        )
        if not activity_type:
            # mail.activity requires an activity type; without the default To-Do
            # type there is nothing valid to schedule — skip rather than crash
            # the daily cron with a NOT NULL violation.
            _logger.warning(
                "Benefit review cron: default activity type missing, skipping."
            )
            return
        activity_type_id = activity_type.id
        # Batch the dedup lookup: one search over all candidate benefits instead
        # of one query per benefit. Existing reminders are keyed on
        # (res_id, user_id) — the same pair used when creating below.
        existing = self.env["mail.activity"].search(
            [
                ("res_model", "=", self._name),
                ("res_id", "in", benefits.ids),
                ("activity_type_id", "=", activity_type_id),
            ]
        )
        already_scheduled = {(act.res_id, act.user_id.id) for act in existing}
        model_id = self.env["ir.model"]._get_id(self._name)
        vals_list = [
            {
                "res_model_id": model_id,
                "res_id": benefit.id,
                "activity_type_id": activity_type_id,
                "user_id": benefit.accountable_id.id,
                "date_deadline": benefit.review_date,
                "summary": f"Benefit review: {benefit.name}",
            }
            for benefit in benefits
            if (benefit.id, benefit.accountable_id.id) not in already_scheduled
        ]
        self.env["mail.activity"].create(vals_list)
        _logger.info("Benefit review cron: scheduled %d activities", len(vals_list))

    @api.depends("target_value", "actual_value")
    def _compute_achievement_pct(self) -> None:
        """Compute achievement as actual/target percentage."""
        for benefit in self:
            if benefit.target_value:
                benefit.achievement_pct = (
                    benefit.actual_value / benefit.target_value
                ) * 100
            else:
                benefit.achievement_pct = 0.0
