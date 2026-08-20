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
    _inherit = ["mixin.mail.thread"]

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
    # Recorded when the sprint closes: the unfinished work is detached from the
    # sprint at that moment, so without this its commitment is unrecoverable.
    carried_over_count = fields.Integer(
        "Carried Over",
        readonly=True,
        copy=False,
        help="Tasks still unfinished when this sprint closed, returned to the "
        "backlog. Counted in the sprint's commitment, not in its velocity.",
    )
    carried_over_hours = fields.Float(
        "Carried Over Hours",
        readonly=True,
        copy=False,
        export_string_translation=False,
    )
    carried_over_story_points = fields.Float(
        "Carried Over Story Points",
        readonly=True,
        copy=False,
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
        "state",
        "carried_over_count",
    )
    def _compute_task_metrics(self) -> None:
        """Compute sprint metrics from task data.

        Closing a sprint detaches whatever was not finished, so a closed
        sprint's ``task_ids`` holds only the delivered work: computing
        completion from it reported 100% for every closed sprint, however much
        was carried over. The counts recorded at closure are added back, which
        is what velocity and carry-over analysis need.
        """
        for sprint in self:
            tasks = sprint.task_ids
            closed = tasks.filtered(lambda t: t.state in CLOSED_STATES)
            carried = sprint.carried_over_count
            sprint.task_count = len(tasks) + carried
            sprint.completed_count = len(closed)
            sprint.completion_pct = (
                len(closed) / sprint.task_count * 100 if sprint.task_count else 0.0
            )
            sprint.committed_hours = (
                sum(tasks.mapped("planned_hours")) + sprint.carried_over_hours
            )
            sprint.velocity = sum(closed.mapped("planned_hours"))
            # Story points — only if tasks have the field populated
            sprint.story_points_committed = (
                sum(tasks.mapped("story_points")) + sprint.carried_over_story_points
            )
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
        """Close the sprint, returning unfinished work to the backlog.

        The unfinished tasks lose their ``sprint_id`` so they can be pulled
        into the next sprint (it is a Many2one), which erased the record of
        what this sprint had committed to. Their weight is recorded first so
        the sprint keeps an honest denominator.
        """
        self.ensure_one()
        incomplete = self.task_ids.filtered(lambda t: t.state not in CLOSED_STATES)
        self.write(
            {
                "carried_over_count": len(incomplete),
                "carried_over_hours": sum(incomplete.mapped("planned_hours")),
                "carried_over_story_points": sum(incomplete.mapped("story_points")),
                "state": "closed",
            }
        )
        if incomplete:
            incomplete.write({"sprint_id": False})
