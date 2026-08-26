import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class ProjectBenefit(models.Model):
    _name = "project.benefit"
    _description = "Project Benefit"
    _order = "sequence, id"
    _inherit = ["mixin.mail.thread", "mixin.mail.activity"]

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
    review_reminder_date = fields.Date(
        "Reminder Scheduled For",
        copy=False,
        help="Internal: the review_date for which a reminder activity was last "
        "scheduled by the cron. Prevents re-nagging every day once a reminder "
        "has been raised; a new reminder is only scheduled when review_date moves.",
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
        today = fields.Date.context_today(self)
        benefits = self.search(
            [
                ("review_date", "<=", today),
                ("state", "in", ("expected", "tracking")),
                ("accountable_id", "!=", False),
            ]
        )
        benefits = benefits.filtered(lambda b: b.review_reminder_date != b.review_date)
        if not benefits:
            return

        activity_type = self.env.ref(
            "mail.mail_activity_data_todo", raise_if_not_found=False
        )
        if not activity_type:
            _logger.warning(
                "Benefit review cron: default activity type missing, skipping."
            )
            return
        scheduled = 0
        for benefit in benefits:
            benefit.activity_schedule(
                "mail.mail_activity_data_todo",
                date_deadline=benefit.review_date,
                summary=self.env._("Benefit review: %s", benefit.name),
                user_id=benefit.accountable_id.id,
            )
            benefit.review_reminder_date = benefit.review_date
            scheduled += 1
        _logger.info("Benefit review cron: scheduled %d activities", scheduled)

    @api.depends("target_value", "actual_value")
    def _compute_achievement_pct(self) -> None:
        for benefit in self:
            if benefit.target_value:
                benefit.achievement_pct = (
                    benefit.actual_value / benefit.target_value
                ) * 100
            else:
                benefit.achievement_pct = 0.0
