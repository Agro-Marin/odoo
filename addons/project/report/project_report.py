"""Tasks analysis report (SQL view)."""

from odoo import fields, models, tools

from odoo.addons.rating.models.rating_data import RATING_LIMIT_MIN


class ReportProjectTaskUser(models.Model):
    """Aggregated task analysis report for project managers."""

    _name = "report.project.task.user"
    _description = "Tasks Analysis"
    _order = "name desc, project_id"
    _auto = False

    name = fields.Char(string="Task Title", readonly=True)
    user_ids = fields.Many2many(
        "res.users",
        relation="project_task_user_rel",
        column1="task_id",
        column2="user_id",
        string="Assignees",
        readonly=True,
    )
    create_date = fields.Datetime("Create Date", readonly=True)
    date_assign = fields.Datetime(string="Assignment Date", readonly=True)
    date_closed = fields.Datetime(string="Closed Date", readonly=True)
    date_end = fields.Datetime(string="Deadline", readonly=True)
    date_last_status_change = fields.Datetime(
        string="Last Status Change", readonly=True
    )
    display_in_project = fields.Boolean(export_string_translation=False)
    project_id = fields.Many2one("project.project", string="Project", readonly=True)
    lead_time_days = fields.Float(
        string="Lead Time (days)",
        digits=(16, 2),
        readonly=True,
        aggregator="avg",
    )
    queue_time_days = fields.Float(
        string="Queue Time (days)",
        digits=(16, 2),
        readonly=True,
        aggregator="avg",
    )
    delay_endings_days = fields.Float(
        string="Days to Deadline",
        digits=(16, 2),
        aggregator="avg",
        readonly=True,
    )
    nbr = fields.Integer("# of Tasks", readonly=True)
    queue_time_hours = fields.Float(
        string="Queue Time (hours)",
        digits=(16, 2),
        readonly=True,
        aggregator="avg",
    )
    lead_time_hours = fields.Float(
        string="Lead Time (hours)",
        digits=(16, 2),
        readonly=True,
        aggregator="avg",
    )
    rating_last_value = fields.Float(
        "Last Rating (1-5)", aggregator="avg", readonly=True
    )
    rating_avg = fields.Float("Average Rating (1-5)", readonly=True, aggregator="avg")
    priority = fields.Selection(
        [
            ("0", "Normal"),
            ("1", "Important"),
            ("2", "High"),
            ("3", "Urgent"),
        ],
        readonly=True,
        string="Priority",
    )

    state = fields.Selection(
        [
            ("in_progress", "In Progress"),
            ("done", "Done"),
            ("waiting", "Waiting"),
            ("approved", "Approved"),
            ("canceled", "Canceled"),
            ("changes_requested", "Changes Requested"),
        ],
        string="State",
        readonly=True,
    )
    is_closed = fields.Boolean(string="Closed state", readonly=True)
    company_id = fields.Many2one("res.company", string="Company", readonly=True)
    partner_id = fields.Many2one("res.partner", string="Customer", readonly=True)
    step_id = fields.Many2one(
        "project.workflow.step", string="Workflow Step", readonly=True
    )
    task_id = fields.Many2one("project.task", string="Task", readonly=True)
    tag_ids = fields.Many2many(
        "project.tags",
        relation="project_tags_project_task_rel",
        column1="project_task_id",
        column2="project_tags_id",
        string="Tags",
        readonly=True,
    )
    parent_id = fields.Many2one("project.task", string="Parent Task", readonly=True)
    milestone_id = fields.Many2one("project.milestone", readonly=True)
    message_is_follower = fields.Boolean(related="task_id.message_is_follower")
    successor_ids = fields.Many2many(
        "project.task",
        relation="project_task_dependency_rel",
        column1="depends_on_id",
        column2="task_id",
        string="Block",
        readonly=True,
        domain="[('allow_dependencies', '=', True), ('id', '!=', id)]",
    )
    description = fields.Text(readonly=True)
    is_template = fields.Boolean(readonly=True)
    has_template_ancestor = fields.Boolean(readonly=True)

    def _select(self) -> str:
        return """
                (select 1) AS nbr,
                t.id as id,
                t.id as task_id,
                t.create_date,
                t.date_assign,
                t.date_closed,
                t.date_last_status_change,
                t.date_end,
                t.display_in_project,
                t.project_id,
                t.priority,
                t.name as name,
                t.company_id,
                t.partner_id,
                t.parent_id,
                t.step_id,
                t.state,
                t.milestone_id,
                CASE WHEN t.state IN ('done', 'canceled') THEN True ELSE False END AS is_closed,
                CASE WHEN pm.id IS NOT NULL THEN true ELSE false END as has_late_and_unreached_milestone,
                t.description,
                NULLIF(t.rating_last_value, 0) as rating_last_value,
                AVG(rt.rating) as rating_avg,
                NULLIF(t.lead_time_days, 0) as lead_time_days,
                NULLIF(t.queue_time_days, 0) as queue_time_days,
                NULLIF(t.queue_time_hours, 0) as queue_time_hours,
                NULLIF(t.lead_time_hours, 0) as lead_time_hours,
                (extract('epoch' from (t.date_end-(now() at time zone 'UTC'))))/(3600*24) as delay_endings_days,
                COUNT(td.task_id) as successor_ids_count,
                t.is_template,
                t.has_template_ancestor
        """

    def _group_by(self) -> str:
        return """
                t.id,
                t.create_date,
                t.date_assign,
                t.date_closed,
                t.date_last_status_change,
                t.date_end,
                t.project_id,
                t.priority,
                t.name,
                t.company_id,
                t.partner_id,
                t.parent_id,
                t.step_id,
                t.state,
                t.rating_last_value,
                t.lead_time_days,
                t.queue_time_days,
                t.queue_time_hours,
                t.lead_time_hours,
                t.milestone_id,
                pm.id,
                td.depends_on_id
        """

    def _from(self) -> str:
        return f"""
                project_task t
                    LEFT JOIN rating_rating rt ON rt.res_id = t.id
                          AND rt.res_model = 'project.task'
                          AND rt.consumed = True
                          AND rt.rating >= {RATING_LIMIT_MIN}
                    LEFT JOIN project_milestone pm ON pm.id = t.milestone_id
                          AND pm.is_reached = False
                          AND pm.deadline <= CAST(now() AS DATE)
                    LEFT JOIN project_task_dependency_rel td ON td.depends_on_id = t.id
                    LEFT JOIN project_project p ON p.id = t.project_id
        """

    def _where(self) -> str:
        return """
                t.project_id IS NOT NULL
        """

    def init(self) -> None:
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(
            """
    CREATE view %s as
         SELECT %s
           FROM %s
          WHERE %s
       GROUP BY %s
        """
            % (
                self._table,
                self._select(),
                self._from(),
                self._where(),
                self._group_by(),
            )
        )
