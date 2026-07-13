"""Shared Kanban workflow steps (PMI terminology alignment).

Each project defines its own ordered set of steps; tasks move through them
as work progresses (e.g. Backlog → In Review → Done). This model replaces
the shared-stage half of the legacy ``project.task.type`` god-model.
"""

from datetime import timedelta
from typing import Any

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ProjectWorkflowStep(models.Model):
    """A named position on a project's Kanban board.

    Steps are shared across projects via the ``project_ids`` Many2many. Tasks
    move through steps to reflect WHERE in the process they are. This is
    distinct from task *state* (the internal condition) and personal *triage*
    (the assignee's time-horizon bucket).
    """

    _name = "project.workflow.step"
    _description = "Workflow Step"
    _inherit = ["project.pm.mixin"]
    _order = "sequence, id"

    def _get_default_project_ids(self) -> list[int] | None:
        """Return the current project as default when created from a project context."""
        default_project_id = self.env.context.get("default_project_id")
        return [default_project_id] if default_project_id else None

    active = fields.Boolean("Active", default=True, export_string_translation=False)
    name = fields.Char(string="Name", required=True, translate=True)
    sequence = fields.Integer(default=1)
    user_id = fields.Many2one(
        "res.users",
        string="Personal Stage Owner",
        ondelete="cascade",
        help=(
            "When set, this step is a personal stage visible only to this user. "
            "Personal stages and project stages are mutually exclusive."
        ),
    )
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
    def create(self, vals_list: list[dict]) -> ProjectWorkflowStep:
        """Enforce mutual exclusivity between personal and project stages.

        If ``project_ids`` is set, ``user_id`` is cleared.  If neither is
        provided, ``user_id`` defaults to the current user (personal stage).
        """
        for vals in vals_list:
            if vals.get("project_ids"):
                vals.pop("user_id", None)
            elif "user_id" not in vals:
                vals["user_id"] = self.env.uid
        records = super().create(vals_list)
        records._seed_rating_deadlines()
        return records

    def write(self, vals: dict) -> bool:
        """Enforce mutual exclusivity between personal and project stages.

        Setting ``project_ids`` clears ``user_id``.  Setting ``user_id`` on a
        step that already has ``project_ids`` (without clearing them) raises.
        """
        if vals.get("project_ids"):
            # project_ids takes precedence — always clear user_id. Emptying
            # project_ids intentionally leaves user_id False (a project stage is
            # NOT turned into a personal stage — see test_modify_existing_stage).
            vals["user_id"] = False
        elif vals.get("user_id") and "project_ids" not in vals:
            for step in self:
                if step.project_ids:
                    raise UserError(
                        _(
                            "Cannot set a personal owner on a project stage. "
                            "Remove the project association first."
                        )
                    )
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
            # Only the tasks currently IN this step, not every task of the
            # project: _send_task_rating_mail keys off each task's own step, so
            # blasting the whole project fires premature requests for tasks that
            # sit in other (not-yet-due) periodic steps.
            step.project_ids.task_ids.filtered(
                lambda t, step=step: t.step_id == step
            )._send_task_rating_mail()
            step.rating_request_deadline = step._next_rating_deadline()
            self.env.cr.commit()
