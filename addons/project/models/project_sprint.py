"""Sprint (time-boxed iteration) management.

Evidence basis: Shape Up (6-week cycles), Scrum sprints, and flow-based
cadences all share the same principle — time-boxing forces prioritization
and prevents scope creep within an iteration. The evidence on sprint-based
vs flow-based is mixed; what matters is rhythm, not the specific mechanism.
Feature-flagged via ``use_sprints`` on project.
"""

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.translate import _

from .project_task import CLOSED_STATES


class ProjectSprint(models.Model):
    """A time-boxed iteration within a project."""

    _name = "project.sprint"
    _description = "Sprint"
    _order = "date_start desc, id desc"
    _inherit = ["mail.thread"]

    name = fields.Char("Sprint Name", required=True, tracking=True)
    project_id = fields.Many2one(
        "project.project",
        required=True,
        ondelete="cascade",
        index=True,
    )
    date_start = fields.Date("Start Date", required=True, tracking=True)
    date_end = fields.Date("End Date", required=True, tracking=True)
    goal = fields.Text(
        "Sprint Goal",
        help="One-sentence description of what this sprint aims to achieve.",
    )
    state = fields.Selection(
        [
            ("planning", "Planning"),
            ("active", "Active"),
            ("review", "Review"),
            ("closed", "Closed"),
        ],
        default="planning",
        required=True,
        tracking=True,
    )
    capacity_hours = fields.Float(
        "Team Capacity (hours)",
        help="Total team hours available for this sprint.",
    )
    task_ids = fields.One2many(
        "project.task",
        "sprint_id",
        string="Sprint Tasks",
    )
    task_count = fields.Integer(
        "Tasks",
        compute="_compute_task_metrics",
        export_string_translation=False,
    )
    completed_count = fields.Integer(
        "Completed",
        compute="_compute_task_metrics",
        export_string_translation=False,
    )
    completion_pct = fields.Float(
        "Completion %",
        compute="_compute_task_metrics",
        export_string_translation=False,
    )
    committed_hours = fields.Float(
        "Committed Hours",
        compute="_compute_task_metrics",
        help="Sum of planned_hours for all sprint tasks (PMI scope baseline).",
        export_string_translation=False,
    )
    velocity = fields.Float(
        "Velocity (hours)",
        compute="_compute_task_metrics",
        help="Sum of planned_hours for completed sprint tasks.",
        export_string_translation=False,
    )
    story_points_committed = fields.Float(
        "Story Points Committed",
        compute="_compute_task_metrics",
        export_string_translation=False,
    )
    story_points_completed = fields.Float(
        "Story Points Completed",
        compute="_compute_task_metrics",
        export_string_translation=False,
    )

    _sprint_date_check = models.Constraint(
        "check(date_end >= date_start)",
        "Sprint end date must be after start date.",
    )
    _unique_active_sprint = models.UniqueIndex(
        "(project_id) WHERE (state = 'active')",
        "A project can only have one active sprint at a time.",
    )

    @api.depends(
        "task_ids",
        "task_ids.state",
        "task_ids.planned_hours",
        "task_ids.story_points",
    )
    def _compute_task_metrics(self) -> None:
        """Compute sprint metrics from task data."""
        for sprint in self:
            tasks = sprint.task_ids
            closed = tasks.filtered(lambda t: t.state in CLOSED_STATES)
            sprint.task_count = len(tasks)
            sprint.completed_count = len(closed)
            sprint.completion_pct = len(closed) / len(tasks) * 100 if tasks else 0.0
            sprint.committed_hours = sum(tasks.mapped("planned_hours"))
            sprint.velocity = sum(closed.mapped("planned_hours"))
            # Story points — only if tasks have the field populated
            sprint.story_points_committed = sum(tasks.mapped("story_points"))
            sprint.story_points_completed = sum(closed.mapped("story_points"))

    def action_start(self) -> None:
        """Activate this sprint, ensuring only one is active per project."""
        self.ensure_one()
        active_sprints = self.search(
            [
                ("project_id", "=", self.project_id.id),
                ("state", "=", "active"),
                ("id", "!=", self.id),
            ]
        )
        if active_sprints:
            raise ValidationError(
                _(
                    "Project '%(project)s' already has an active sprint: %(sprint)s",
                    project=self.project_id.name,
                    sprint=active_sprints[0].name,
                )
            )
        self.state = "active"

    def action_close(self) -> None:
        """Close this sprint and clear sprint_id on incomplete tasks."""
        self.ensure_one()
        incomplete = self.task_ids.filtered(lambda t: t.state not in CLOSED_STATES)
        if incomplete:
            incomplete.write({"sprint_id": False})
        self.state = "closed"
