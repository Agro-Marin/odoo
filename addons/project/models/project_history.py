"""Historical project data for reference class forecasting.

Evidence basis: Flyvbjerg (16,000 projects) — reference class forecasting
is the strongest antidote to the planning fallacy. Kahneman: the 'outside
view' corrects systematic optimism bias.
"""

from odoo import Command, api, fields, models


class ProjectHistory(models.Model):
    """Archived project metrics for reference class comparison."""

    _name = "project.history"
    _description = "Project History"
    _order = "date_completed desc, id desc"

    project_id = fields.Many2one(
        "project.project",
        ondelete="set null",
        index=True,
        help="Link to the original project (may be archived or deleted).",
    )
    name = fields.Char(
        "Project Name (snapshot)",
        required=True,
        help="Frozen project name at time of archival.",
    )
    date_completed = fields.Date("Date Completed", required=True)
    date_start = fields.Date("Date Started")
    planned_duration_days = fields.Integer(
        "Planned Duration (days)",
        help="Days from date_start to planned end date.",
    )
    actual_duration_days = fields.Integer(
        "Actual Duration (days)",
        help="Days from date_start to actual completion.",
    )
    duration_variance_pct = fields.Float(
        "Duration Variance %",
        compute="_compute_variances",
        store=True,
        help="(actual - planned) / planned * 100. Positive = over-schedule.",
        export_string_translation=False,
    )
    planned_hours = fields.Float("Planned Hours (sum of task.planned_hours)")
    actual_hours = fields.Float(
        "Actual Hours",
        help="Sum of effective_hours (requires timesheet module).",
    )
    hours_variance_pct = fields.Float(
        "Hours Variance %",
        compute="_compute_variances",
        store=True,
        help="(actual - planned) / planned * 100. Positive = over-budget.",
        export_string_translation=False,
    )
    task_count = fields.Integer("Total Tasks")
    team_size = fields.Integer("Team Size (distinct assignees)")
    tag_ids = fields.Many2many(
        "project.tags",
        "project_history_tags_rel",
        "history_id",
        "tag_id",
        string="Tags",
        help="Copied from project tags for reference class search.",
    )
    avg_lead_time = fields.Float(
        "Avg Lead Time (hours)",
        help="Average lead_time_hours (create→end) at project completion.",
    )
    avg_cycle_time = fields.Float(
        "Avg Cycle Time (hours)",
        help="Average cycle_time_hours (assign→end) at project completion.",
    )
    deadline_compliance_pct = fields.Float(
        "Deadline Compliance %",
        help="Percentage of tasks that met their deadlines.",
    )

    @api.depends(
        "planned_duration_days",
        "actual_duration_days",
        "planned_hours",
        "actual_hours",
    )
    def _compute_variances(self) -> None:
        """Compute schedule and effort variance percentages."""
        for rec in self:
            if rec.planned_duration_days:
                rec.duration_variance_pct = (
                    (rec.actual_duration_days - rec.planned_duration_days)
                    / rec.planned_duration_days
                    * 100
                )
            else:
                rec.duration_variance_pct = 0.0
            if rec.planned_hours:
                rec.hours_variance_pct = (
                    (rec.actual_hours - rec.planned_hours) / rec.planned_hours * 100
                )
            else:
                rec.hours_variance_pct = 0.0

    @api.model
    def create_from_project(self, project) -> ProjectHistory:
        """Create a history record by snapshotting a completed project."""
        task_domain = [
            ("project_id", "=", project.id),
            ("is_template", "=", False),
        ]
        Task = self.env["project.task"]
        tasks = Task.search(task_domain)

        # Compute team size from distinct assignees
        assignees = set()
        for task in tasks:
            assignees.update(task.user_ids.ids)

        # Planned duration
        planned_days = 0
        if project.date_start and project.date:
            planned_days = (project.date - project.date_start).days

        # Actual completion = when the project's work really finished (latest
        # task closure), NOT when this snapshot happens to be taken. Otherwise a
        # project archived months after it ended records an inflated duration,
        # corrupting the reference-class forecasting this model feeds.
        closed_tasks = tasks.filtered(lambda t: t.state in ("done", "canceled"))
        closed_dates = closed_tasks.filtered("date_closed").mapped("date_closed")
        completion_date = (
            max(closed_dates).date() if closed_dates else fields.Date.today()
        )

        actual_days = 0
        if project.date_start:
            actual_days = (completion_date - project.date_start).days

        # Aggregate hours (PMI: scope baseline = sum of estimates).
        planned_hours = sum(tasks.mapped("planned_hours"))

        # Actual hours — only available if timesheet module installed
        actual_hours = 0.0
        if "effective_hours" in Task._fields:
            actual_hours = sum(tasks.mapped("effective_hours"))
        avg_lt = 0.0
        avg_ct = 0.0
        if closed_tasks:
            lt_values = [t.lead_time_hours for t in closed_tasks if t.lead_time_hours]
            avg_lt = sum(lt_values) / len(lt_values) if lt_values else 0.0
            ct_values = [t.cycle_time_hours for t in closed_tasks if t.cycle_time_hours]
            avg_ct = sum(ct_values) / len(ct_values) if ct_values else 0.0

        dl_tasks = closed_tasks.filtered("date_end")
        dl_pct = 0.0
        if dl_tasks:
            met = dl_tasks.filtered(
                lambda t: t.date_closed and t.date_closed <= t.date_end
            )
            dl_pct = len(met) / len(dl_tasks) * 100

        return self.create(
            {
                "project_id": project.id,
                "name": project.name,
                "date_completed": completion_date,
                "date_start": project.date_start,
                "planned_duration_days": planned_days,
                "actual_duration_days": actual_days,
                "planned_hours": planned_hours,
                "actual_hours": actual_hours,
                "task_count": len(tasks),
                "team_size": len(assignees),
                "tag_ids": [Command.set(project.tag_ids.ids)],
                "avg_lead_time": avg_lt,
                "avg_cycle_time": avg_ct,
                "deadline_compliance_pct": dl_pct,
            }
        )
