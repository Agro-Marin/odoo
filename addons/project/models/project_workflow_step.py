"""Shared Kanban workflow steps (PMI terminology alignment).

Each project defines its own ordered set of steps; tasks move through them
as work progresses (e.g. Backlog → In Review → Done). This model replaces
the shared-stage half of the legacy ``project.task.type`` god-model.
"""

from datetime import timedelta

from odoo import _, api, fields, models


class ProjectWorkflowStep(models.Model):
    """A named position on a project's Kanban board.

    Steps are shared across projects via the ``project_ids`` Many2many. Tasks
    move through steps to reflect WHERE in the process they are. This is
    distinct from task *state* (the internal condition) and personal *triage*
    (the assignee's time-horizon bucket).
    """

    _name = "project.workflow.step"
    _description = "Workflow Step"
    _order = "sequence, id"

    def _get_default_project_ids(self) -> list[int] | None:
        """Return the current project as default when created from a project context."""
        default_project_id = self.env.context.get("default_project_id")
        return [default_project_id] if default_project_id else None

    active = fields.Boolean("Active", default=True, export_string_translation=False)
    name = fields.Char(string="Name", required=True, translate=True)
    sequence = fields.Integer(default=1)
    project_ids = fields.Many2many(
        "project.project",
        "project_workflow_step_project_rel",
        "step_id",
        "project_id",
        string="Projects",
        default=lambda self: self._get_default_project_ids(),
        help=(
            "Projects that use this workflow step. Steps can be shared across "
            "projects with similar processes to consolidate reporting."
        ),
    )
    mail_template_id = fields.Many2one(
        "mail.template",
        string="Email Template",
        domain=[("model", "=", "project.task")],
        help="Email sent automatically when a task enters this step.",
    )
    color = fields.Integer(string="Color", export_string_translation=False)
    fold = fields.Boolean(string="Folded")
    rating_template_id = fields.Many2one(
        "mail.template",
        string="Rating Email Template",
        domain=[("model", "=", "project.task")],
        help=(
            "Rating request sent automatically when a task enters this step, "
            "or at a regular interval while the task remains here."
        ),
    )
    auto_update_state = fields.Boolean(
        "Auto-update State on Rating",
        default=False,
        help=(
            "Automatically update the task state based on customer rating replies:\n"
            " * Good feedback → Approved (green bullet).\n"
            " * Neutral or bad feedback → Changes Requested (orange bullet)."
        ),
    )
    rotting_threshold_days = fields.Integer(
        "Days to Rot",
        default=0,
        help=(
            "Number of days of inactivity before tasks in this step are marked "
            "as stale. Set to 0 to disable."
        ),
    )
    rating_request_deadline = fields.Datetime(
        compute="_compute_rating_request_deadline",
        store=True,
        export_string_translation=False,
    )
    rating_active = fields.Boolean("Send a Customer Rating Request")
    rating_status = fields.Selection(
        string="Customer Ratings Status",
        selection=[
            ("stage", "When reaching this step"),
            ("periodic", "On a periodic basis"),
        ],
        default="stage",
        required=True,
        help=(
            "When to send the rating request:\n"
            " * When reaching this step: sent once on step entry.\n"
            " * On a periodic basis: sent at the configured interval."
        ),
    )
    rating_status_period = fields.Selection(
        string="Rating Frequency",
        selection=[
            ("daily", "Daily"),
            ("weekly", "Weekly"),
            ("bimonthly", "Twice a Month"),
            ("monthly", "Once a Month"),
            ("quarterly", "Quarterly"),
            ("yearly", "Yearly"),
        ],
        default="monthly",
        required=True,
    )

    @api.depends("rating_status", "rating_status_period")
    def _compute_rating_request_deadline(self) -> None:
        """Compute the next scheduled rating request deadline."""
        periods = {
            "daily": 1,
            "weekly": 7,
            "bimonthly": 15,
            "monthly": 30,
            "quarterly": 90,
            "yearly": 365,
        }
        for step in self:
            step.rating_request_deadline = fields.Datetime.now() + timedelta(
                days=periods.get(step.rating_status_period, 0)
            )

    def copy_data(self, default: dict | None = None) -> list[dict]:
        """Append '(copy)' to the name when duplicating a workflow step."""
        vals_list = super().copy_data(default=default)
        return [
            dict(vals, name=self.env._("%s (copy)", step.name))
            for step, vals in zip(self, vals_list, strict=True)
        ]

    @api.model
    def _send_rating_all(self) -> None:
        """Send periodic rating requests for all eligible steps.

        Called once per day by the scheduler.
        """
        steps = self.search(
            [
                ("rating_active", "=", True),
                ("rating_status", "=", "periodic"),
                ("rating_request_deadline", "<=", fields.Datetime.now()),
            ]
        )
        for step in steps:
            step.project_ids.task_ids._send_task_rating_mail()
            step._compute_rating_request_deadline()
            self.env.cr.commit()
