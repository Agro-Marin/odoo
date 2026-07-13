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
    project_id = fields.Many2one("project.project", string="Project", readonly=True)
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
        help=(
            "True when the user's busiest single week exceeds 40 allocated "
            "hours across all active projects (reservations are bucketed by "
            "ISO week on their start date)."
        ),
    )

    def init(self) -> None:
        """Create the SQL view for resource utilization.

        Sources ``allocated_hours`` from ``resource_reservation`` (per-resource
        ledger) — NOT from ``project_task.allocated_hours``, which sums
        across all assignees and would double-count multi-user tasks
        when joined through ``project_task_user_rel``.  See PMI hours
        model: this report measures actual resource commitment, so the
        per-resource reservation row is canonical.
        """
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                WITH reservations AS (
                    SELECT
                        res.user_id,
                        t.project_id,
                        t.id AS task_id,
                        rr.allocated_hours,
                        DATE_TRUNC('week', rr.date_start) AS week_start
                    FROM resource_reservation rr
                    JOIN resource_resource res ON res.id = rr.resource_id
                    JOIN project_task t
                         ON t.id = rr.res_id
                        AND rr.res_model = 'project.task'
                    WHERE t.state NOT IN ('done', 'canceled')
                      AND t.project_id IS NOT NULL
                      AND t.is_template IS NOT TRUE
                      AND t.active = TRUE
                      AND res.user_id IS NOT NULL
                ),
                user_project AS (
                    SELECT
                        user_id,
                        project_id,
                        SUM(allocated_hours) AS allocated_hours,
                        COUNT(DISTINCT task_id) AS task_count
                    FROM reservations
                    GROUP BY user_id, project_id
                ),
                -- Peak weekly load per user: sum hours within each ISO week
                -- (by reservation start date), then take the busiest week.
                user_peak AS (
                    SELECT user_id, MAX(week_hours) AS peak_week_hours
                    FROM (
                        SELECT user_id, week_start, SUM(allocated_hours) AS week_hours
                        FROM reservations
                        WHERE week_start IS NOT NULL
                        GROUP BY user_id, week_start
                    ) w
                    GROUP BY user_id
                ),
                user_totals AS (
                    SELECT user_id, COUNT(DISTINCT project_id) AS project_count
                    FROM user_project
                    GROUP BY user_id
                )
                SELECT
                    ROW_NUMBER() OVER (ORDER BY up.user_id, up.project_id) AS id,
                    up.user_id,
                    up.project_id,
                    up.allocated_hours,
                    up.task_count,
                    ut.project_count,
                    COALESCE(pk.peak_week_hours, 0) > 40 AS is_overallocated
                FROM user_project up
                JOIN user_totals ut ON ut.user_id = up.user_id
                LEFT JOIN user_peak pk ON pk.user_id = up.user_id
            )
        """)
