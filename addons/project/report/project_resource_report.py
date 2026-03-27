"""Cross-project resource utilization report (SQL view).

Evidence basis: queuing theory (at 90% utilization, wait times are 9x
baseline), Flyvbjerg (92% of megaprojects over budget — overcommitment
is the norm). This report makes invisible overallocation visible.
"""

from odoo import fields, models, tools


class ProjectResourceReport(models.Model):
    """Per-user resource allocation across all active projects."""

    _name = "project.resource.report"
    _description = "Resource Utilization"
    _auto = False
    _order = "allocated_hours desc"

    user_id = fields.Many2one("res.users", string="User", readonly=True)
    project_id = fields.Many2one(
        "project.project", string="Project", readonly=True
    )
    allocated_hours = fields.Float(
        "Allocated Hours",
        readonly=True,
        aggregator="sum",
    )
    task_count = fields.Integer(
        "Open Tasks",
        readonly=True,
        aggregator="sum",
    )
    project_count = fields.Integer(
        "Projects",
        readonly=True,
        aggregator="max",
    )
    is_overallocated = fields.Boolean(
        "Overallocated",
        readonly=True,
        help="True when total allocated hours across all projects exceed 40h/week.",
    )

    def init(self) -> None:
        """Create the SQL view for resource utilization."""
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                WITH user_project AS (
                    SELECT
                        rel.user_id,
                        t.project_id,
                        SUM(t.allocated_hours) AS allocated_hours,
                        COUNT(*) AS task_count
                    FROM project_task t
                    JOIN project_task_user_rel rel ON rel.task_id = t.id
                    WHERE t.state NOT IN ('done', 'canceled')
                      AND t.project_id IS NOT NULL
                      AND t.is_template = FALSE
                    GROUP BY rel.user_id, t.project_id
                ),
                user_totals AS (
                    SELECT
                        user_id,
                        COUNT(DISTINCT project_id) AS project_count,
                        SUM(allocated_hours) AS total_hours
                    FROM user_project
                    GROUP BY user_id
                )
                SELECT
                    ROW_NUMBER() OVER () AS id,
                    up.user_id,
                    up.project_id,
                    up.allocated_hours,
                    up.task_count,
                    ut.project_count,
                    ut.total_hours > 40 AS is_overallocated
                FROM user_project up
                JOIN user_totals ut ON ut.user_id = up.user_id
            )
        """)
