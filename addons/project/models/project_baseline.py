"""Project baseline (scope snapshot) for tracking schedule and scope variance.

Evidence basis: Scope creep is one of the most common causes of project
overruns (meta-analyses). Cone of Uncertainty: upfront plans have 4x error
range. Baselines make accumulated slip visible.
"""

from odoo import api, fields, models
from odoo.exceptions import UserError


class ProjectBaseline(models.Model):
    """A point-in-time snapshot of a project's tasks for variance analysis."""

    _name = "project.baseline"
    _description = "Project Baseline"
    _order = "date_created desc, id desc"

    name = fields.Char(
        "Baseline Name",
        required=True,
        help="e.g. 'Original Plan', 'Replan v2'.",
    )
    project_id = fields.Many2one(
        "project.project",
        required=True,
        ondelete="cascade",
        index=True,
    )
    date_created = fields.Datetime(
        "Created On",
        default=fields.Datetime.now,
        readonly=True,
    )
    created_by_id = fields.Many2one(
        "res.users",
        string="Created By",
        default=lambda self: self.env.user,
        readonly=True,
    )
    is_current = fields.Boolean(
        "Current Baseline",
        default=False,
        help="Only one baseline per project can be marked as current.",
    )
    line_ids = fields.One2many(
        "project.baseline.line",
        "baseline_id",
        string="Baseline Lines",
    )
    line_count = fields.Integer(
        "Tasks Snapshot",
        compute="_compute_line_count",
        export_string_translation=False,
    )

    _unique_current_baseline = models.UniqueIndex(
        "(project_id) WHERE (is_current IS TRUE)",
        "Only one baseline per project can be marked as current.",
    )

    @api.depends("line_ids")
    def _compute_line_count(self) -> None:
        for baseline in self:
            baseline.line_count = len(baseline.line_ids)

    def action_set_current(self) -> None:
        """Mark this baseline as the current one, unsetting any previous."""
        self.ensure_one()
        self.project_id.baseline_ids.filtered("is_current").write({"is_current": False})
        self.is_current = True

    def action_capture_snapshot(self) -> None:
        """Create baseline lines from the project's current tasks."""
        self.ensure_one()
        if self.line_ids:
            raise UserError(
                self.env._(
                    "This baseline already has snapshot data. "
                    "Create a new baseline instead."
                )
            )
        tasks = self.env["project.task"].search(
            [
                ("project_id", "=", self.project_id.id),
                ("is_template", "=", False),
            ]
        )
        lines = [
            {
                "baseline_id": self.id,
                "task_id": task.id,
                "task_name": task.name,
                "planned_start": task.date_assign,
                "planned_end": task.date_end,
                "planned_hours": task.planned_hours,
                "milestone_id": task.milestone_id.id,
                "step_id": task.step_id.id,
            }
            for task in tasks
        ]
        self.env["project.baseline.line"].create(lines)


class ProjectBaselineLine(models.Model):
    """A single task's snapshot within a baseline."""

    _name = "project.baseline.line"
    _description = "Baseline Task Snapshot"
    _order = "sequence, id"

    baseline_id = fields.Many2one(
        "project.baseline",
        required=True,
        ondelete="cascade",
        index=True,
    )
    project_id = fields.Many2one(
        related="baseline_id.project_id",
        store=True,
        index=True,
    )
    task_id = fields.Many2one(
        "project.task",
        string="Task",
        ondelete="set null",
        index=True,
        help="Link to the original task (may be deleted since snapshot).",
    )
    task_name = fields.Char("Task Name (snapshot)", required=True)
    sequence = fields.Integer(default=10)
    planned_start = fields.Datetime("Planned Start (snapshot)")
    planned_end = fields.Datetime("Planned End (snapshot)")
    planned_hours = fields.Float("Planned Hours (snapshot)")
    milestone_id = fields.Many2one(
        "project.milestone",
        string="Milestone (snapshot)",
        ondelete="set null",
    )
    step_id = fields.Many2one(
        "project.workflow.step",
        string="Step (snapshot)",
        ondelete="set null",
    )
