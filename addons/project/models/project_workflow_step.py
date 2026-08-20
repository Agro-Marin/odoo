"""Shared Kanban workflow steps (PMI terminology alignment).

Each project defines its own ordered set of steps; tasks move through them
as work progresses (e.g. Backlog → In Review → Done). This model replaces
the shared-stage half of the legacy ``project.task.type`` god-model.
"""

from datetime import timedelta
from typing import Any

from odoo import _, api, fields, models
from odoo.api import ValuesType

from .project_task import CLOSED_STATES


class ProjectWorkflowStep(models.Model):
    """A named position on a project's Kanban board.

    Steps are shared across projects via the ``project_ids`` Many2many. Tasks
    move through steps to reflect WHERE in the process they are. This is
    distinct from task *state* (the internal condition) and personal *triage*
    (the assignee's time-horizon bucket, which is ``project.triage`` — a
    separate model, never a step: see the class comment on ``create``).
    """

    _name = "project.workflow.step"
    _description = "Workflow Step"
    _inherit = ["mixin.project.pm"]
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
    wip_limit = fields.Integer(
        "WIP Limit",
        default=0,
        help=(
            "Maximum number of tasks allowed in this step per project. "
            "0 = no limit. When exceeded, the step header shows a warning."
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
        export_string_translation=False,
        help=(
            "Next scheduled periodic rating request. Seeded when periodic "
            "rating is enabled and advanced after each send — deliberately a "
            "plain field, not a now()-based compute that would reset on every "
            "module upgrade or unrelated recompute."
        ),
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

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> ProjectWorkflowStep:
        """Create steps and seed the first deadline of any periodic rater.

        A step used to carry a ``user_id`` ("Personal Stage Owner") and this
        override enforced that a step was *either* a project step *or* one
        user's personal stage. That invariant died with the model split:
        ``migrations/1.4/pre-migrate.py`` builds this table from
        ``project_task_type`` rows with ``user_id IS NULL`` and routes the
        owned rows to ``project.triage``, which is where personal buckets live
        now. Nothing read the surviving field — no record rule, no view, no
        domain, and ``step_find`` searches ``project_ids`` alone, so an owned
        step could never be found for any task.

        The guard also got the one case that mattered wrong: it inspected
        ``vals["project_ids"]``, while the Kanban "add column" button supplies
        the project through the field *default* (``_get_default_project_ids``
        reading ``default_project_id``). Every column added from a project
        board therefore came out owned *and* attached — the exact state the
        old ``write`` refused to produce.
        """
        records = super().create(vals_list)
        records._seed_rating_deadlines()
        return records

    def write(self, vals: dict) -> bool:
        res = super().write(vals)
        if {"rating_active", "rating_status", "rating_status_period"} & vals.keys():
            self._seed_rating_deadlines()
        return res

    def unlink_wizard(self, stage_view: bool = False) -> dict[str, Any]:
        """Open the delete/archive confirmation wizard for these workflow steps."""
        wizard = self.env["project.workflow.step.delete.wizard"].create(
            {
                "project_ids": self.project_ids.ids,
                "step_ids": self.ids,
            }
        )
        context = dict(self.env.context, stage_view=stage_view)
        return {
            "name": _("Delete Workflow Step"),
            "view_mode": "form",
            "res_model": "project.workflow.step.delete.wizard",
            "views": [
                (
                    self.env.ref("project.view_project_workflow_step_delete_wizard").id,
                    "form",
                )
            ],
            "type": "ir.actions.act_window",
            "res_id": wizard.id,
            "target": "new",
            "context": context,
        }

    _RATING_PERIOD_DAYS = {
        "daily": 1,
        "weekly": 7,
        "bimonthly": 15,
        "monthly": 30,
        "quarterly": 90,
        "yearly": 365,
    }

    def _next_rating_deadline(self):
        """Return now + the step's configured rating period."""
        self.ensure_one()
        return fields.Datetime.now() + timedelta(
            days=self._RATING_PERIOD_DAYS.get(self.rating_status_period, 0)
        )

    def _seed_rating_deadlines(self) -> None:
        """Set the first deadline for steps that just became periodic raters."""
        for step in self:
            if (
                step.rating_active
                and step.rating_status == "periodic"
                and not step.rating_request_deadline
            ):
                step.rating_request_deadline = step._next_rating_deadline()

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
            step._get_rating_tasks()._send_task_rating_mail()
            step.rating_request_deadline = step._next_rating_deadline()
            self.env.cr.commit()

    def _get_rating_tasks(self):
        """The tasks a periodic rating request should go to for this step.

        Only the tasks currently IN this step, not every task of the project:
        ``_send_task_rating_mail`` keys off each task's own step, so blasting
        the whole project fires premature requests for tasks sitting in other
        (not-yet-due) periodic steps. Searching the step's tasks directly also
        avoids materialising every task of every linked project.

        Open tasks only. A periodic rater asks "how is this going?" on a
        cadence; a task that is done or cancelled is not going anywhere, and
        because it keeps sitting in the step the request repeated for as long
        as the step existed. (Archived tasks are already excluded by the
        default ``active_test``.)

        Split out of ``_send_rating_all`` so the selection can be tested: that
        method commits once per step, which a test cursor forbids outright, so
        the scope had no way of being pinned through the cron entry point.
        """
        self.ensure_one()
        return self.env["project.task"].search(
            [
                ("step_id", "=", self.id),
                ("state", "not in", list(CLOSED_STATES)),
            ]
        )
