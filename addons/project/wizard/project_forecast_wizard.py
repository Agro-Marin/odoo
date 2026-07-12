"""Monte Carlo forecast wizard using historical throughput data.

Evidence basis: Spolsky's Evidence-Based Scheduling, probabilistic
forecasting from Kanban analytics. Uses random sampling from actual
weekly throughput history to simulate completion dates.
"""

import random
from datetime import timedelta

from odoo import api, fields, models
from odoo.tools import SQL


class ProjectForecastWizard(models.TransientModel):
    """Run Monte Carlo simulation to forecast project completion dates."""

    _name = "project.forecast.wizard"
    _description = "Monte Carlo Forecast"

    project_id = fields.Many2one(
        "project.project",
        string="Project",
        required=True,
        default=lambda self: self.env.context.get("active_id"),
    )
    remaining_items = fields.Integer(
        "Remaining Items",
        compute="_compute_remaining_items",
        readonly=False,
        store=True,
        help="Number of tasks to complete. Defaults to open task count.",
    )
    simulation_count = fields.Integer(
        "Simulations",
        default=1000,
        help="Number of Monte Carlo iterations (more = more accurate).",
    )
    weeks_of_history = fields.Integer(
        "Weeks of History",
        default=12,
        help="How many weeks of throughput data to sample from.",
    )
    # Results
    p50_weeks = fields.Float("50th Percentile (weeks)", readonly=True, digits=(5, 1))
    p85_weeks = fields.Float("85th Percentile (weeks)", readonly=True, digits=(5, 1))
    p95_weeks = fields.Float("95th Percentile (weeks)", readonly=True, digits=(5, 1))
    result_text = fields.Text("Forecast Summary", readonly=True)

    @api.depends("project_id")
    def _compute_remaining_items(self) -> None:
        for wiz in self:
            if wiz.project_id:
                wiz.remaining_items = wiz.project_id.open_task_count
            else:
                wiz.remaining_items = 0

    def action_run_forecast(self) -> dict:
        """Run the Monte Carlo simulation and display results."""
        self.ensure_one()
        if not self.remaining_items or self.remaining_items <= 0:
            self.result_text = "No remaining items to forecast."
            return self._reopen_wizard()

        # Fetch weekly throughput history
        throughput = self._get_weekly_throughput()
        if not throughput or all(t == 0 for t in throughput):
            self.result_text = (
                "No historical throughput data available. "
                "Close some tasks to build forecasting data."
            )
            return self._reopen_wizard()

        # Run simulation
        results = []
        for _i in range(self.simulation_count):
            weeks = 0
            remaining = self.remaining_items
            while remaining > 0:
                # Sample a random week's throughput
                weekly_tp = random.choice(throughput)
                remaining -= max(weekly_tp, 0)
                weeks += 1
                if weeks > 200:  # Safety cap
                    break
            results.append(weeks)

        results.sort()
        n = len(results)
        self.p50_weeks = results[int(n * 0.50)]
        self.p85_weeks = results[int(n * 0.85)]
        self.p95_weeks = results[int(n * 0.95)]

        self.result_text = (
            f"Based on {len(throughput)} weeks of throughput data "
            f"({self.simulation_count} simulations):\n\n"
            f"  50% chance of finishing in {self.p50_weeks:.0f} weeks or less\n"
            f"  85% chance of finishing in {self.p85_weeks:.0f} weeks or less\n"
            f"  95% chance of finishing in {self.p95_weeks:.0f} weeks or less\n\n"
            f"Remaining items: {self.remaining_items}\n"
            f"Historical throughput: {min(throughput)}-{max(throughput)} tasks/week "
            f"(avg {sum(throughput) / len(throughput):.1f})"
        )
        return self._reopen_wizard()

    def _get_weekly_throughput(self) -> list[int]:
        """Fetch tasks-closed-per-week for the last N weeks.

        Throughput buckets by ``date_closed`` (the actual completion timestamp),
        not ``date_end`` (the renamed deadline) — forecasting from deadlines
        rather than real closures would be meaningless. The rolling-window
        boundary is computed in Python via ``cr.now()`` (naive UTC, matching the
        column's storage): ``INTERVAL %(param)s`` is not valid SQL (the interval
        text must be a literal, not a bind placeholder) and a bare ``NOW()``
        would be evaluated in the session timezone against a UTC column.
        """
        since = self.env.cr.now() - timedelta(weeks=self.weeks_of_history)
        self.env.cr.execute(
            SQL(
                """
            SELECT
                DATE_TRUNC('week', date_closed) AS week,
                COUNT(*) AS closed_count
            FROM project_task
            WHERE project_id = %(project_id)s
              AND state IN ('done', 'canceled')
              AND date_closed >= %(since)s
              AND date_closed IS NOT NULL
              AND is_template IS NOT TRUE
            GROUP BY DATE_TRUNC('week', date_closed)
            ORDER BY week
            """,
                project_id=self.project_id.id,
                since=since,
            )
        )
        return [row[1] for row in self.env.cr.fetchall()]

    def _reopen_wizard(self) -> dict:
        """Return action to keep the wizard open after running."""
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }
