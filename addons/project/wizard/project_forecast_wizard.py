"""Monte Carlo forecast wizard using historical throughput data.

Evidence basis: Spolsky's Evidence-Based Scheduling, probabilistic
forecasting from Kanban analytics. Uses random sampling from actual
weekly throughput history to simulate completion dates.
"""

import random
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import SQL

from odoo.addons.project.models.project_task import DELIVERED_STATES


class ProjectForecastWizard(models.TransientModel):
    """Run Monte Carlo simulation to forecast project completion dates."""

    _name = "project.forecast.wizard"
    _description = "Monte Carlo Forecast"

    # Bounds a single simulated run. Reached only when the sampled throughput
    # is too slow to clear the backlog; runs that hit it are reported, never
    # silently folded into the percentiles.
    SIMULATION_WEEK_CAP = 200

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
        if self.simulation_count < 1:
            raise UserError(self.env._("The number of simulations must be at least 1."))
        # Cap iterations so a huge user-entered value can't stall the request.
        sim_count = min(self.simulation_count, 100_000)
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
        truncated = 0
        for _i in range(sim_count):
            weeks = 0
            remaining = self.remaining_items
            while remaining > 0:
                # Sample a random week's throughput
                weekly_tp = random.choice(throughput)
                remaining -= max(weekly_tp, 0)
                weeks += 1
                if weeks >= self.SIMULATION_WEEK_CAP:
                    truncated += 1
                    break
            results.append(weeks)

        results.sort()
        n = len(results)
        self.p50_weeks = results[int(n * 0.50)]
        self.p85_weeks = results[int(n * 0.85)]
        self.p95_weeks = results[int(n * 0.95)]

        avg_tp = sum(throughput) / len(throughput)
        lines = [
            self.env._(
                "Based on %(weeks)s weeks of throughput data (%(sims)s simulations):",
                weeks=len(throughput),
                sims=sim_count,
            ),
            "",
            self.env._(
                "  50%% chance of finishing in %(p)s weeks or less",
                p=f"{self.p50_weeks:.0f}",
            ),
            self.env._(
                "  85%% chance of finishing in %(p)s weeks or less",
                p=f"{self.p85_weeks:.0f}",
            ),
            self.env._(
                "  95%% chance of finishing in %(p)s weeks or less",
                p=f"{self.p95_weeks:.0f}",
            ),
            "",
            self.env._("Remaining items: %(n)s", n=self.remaining_items),
            self.env._(
                "Historical throughput: %(lo)s-%(hi)s tasks/week (avg %(avg)s), "
                "including %(zeros)s week(s) with no delivery",
                lo=min(throughput),
                hi=max(throughput),
                avg=f"{avg_tp:.1f}",
                zeros=sum(1 for t in throughput if not t),
            ),
        ]
        # Never let a truncated run masquerade as a finished estimate.
        if truncated:
            lines += [
                "",
                self.env._(
                    "WARNING: %(pct)s%% of simulations had not finished after "
                    "%(cap)s weeks and were cut short — the percentiles above "
                    "are optimistic lower bounds.",
                    pct=f"{100 * truncated / sim_count:.0f}",
                    cap=self.SIMULATION_WEEK_CAP,
                ),
            ]
        self.result_text = "\n".join(lines)
        return self._reopen_wizard()

    def _get_weekly_throughput(self) -> list[int]:
        """Fetch tasks-closed-per-week for the last N weeks, zeros included.

        Every week in the window is a sample, including the ones where nothing
        shipped. A plain ``GROUP BY`` emits no row for an empty week, which
        silently deleted those zeros from the distribution and biased the
        forecast optimistic by the exact factor the feature exists to remove:
        a project delivering in 2 of 12 weeks sampled ``[2, 2]`` and forecast
        10 weeks for 20 items instead of 60 — with P50, P85 and P95 collapsing
        onto one value, because a sample with no variance cannot express any.
        ``generate_series`` supplies the missing weeks.

        Throughput buckets by ``date_closed`` (the actual completion timestamp),
        not ``date_end`` (the renamed deadline) — forecasting from deadlines
        rather than real closures would be meaningless. The rolling-window
        boundary is computed in Python via ``cr.now()`` (naive UTC, matching the
        column's storage): ``INTERVAL %(param)s`` is not valid SQL (the interval
        text must be a literal, not a bind placeholder) and a bare ``NOW()``
        would be evaluated in the session timezone against a UTC column.

        Weeks before the project existed are excluded: they are not evidence
        of slow delivery, and padding with them would bias the forecast
        pessimistic just as dropping the real zeros biased it optimistic. The
        floor is the *earlier* of the project's creation and its first recorded
        closure, so backdated or imported history is never silently discarded.
        """
        # Raw SQL bypasses record rules, and project_id is user-settable on this
        # transient — gate on ORM read access so a user can't read the throughput
        # of a project they are not allowed to see.
        self.project_id.check_access("read")
        since = self.env.cr.now() - timedelta(weeks=self.weeks_of_history)
        self.env.cr.execute(
            SQL(
                """
            WITH closed AS (
                    SELECT DATE_TRUNC('week', date_closed) AS week_start,
                           COUNT(*) AS closed_count
                      FROM project_task
                     WHERE project_id = %(project_id)s
                       AND state IN %(delivered_states)s
                       AND date_closed >= %(since)s
                       AND is_template IS NOT TRUE
                     GROUP BY DATE_TRUNC('week', date_closed)
            ),
            bounds AS (
                    SELECT GREATEST(
                               DATE_TRUNC('week', %(since)s::timestamp),
                               LEAST(
                                   DATE_TRUNC('week', %(project_start)s::timestamp),
                                   COALESCE(
                                       (SELECT MIN(week_start) FROM closed),
                                       DATE_TRUNC('week', %(project_start)s::timestamp)
                                   )
                               )
                           ) AS series_start
            )
            SELECT COALESCE(closed.closed_count, 0) AS closed_count
              FROM bounds,
                   generate_series(
                       bounds.series_start,
                       DATE_TRUNC('week', %(now)s::timestamp),
                       INTERVAL '1 week'
                   ) AS w(week_start)
              LEFT JOIN closed ON closed.week_start = w.week_start
             ORDER BY w.week_start
            """,
                project_id=self.project_id.id,
                delivered_states=DELIVERED_STATES,
                since=since,
                now=self.env.cr.now(),
                project_start=self.project_id.create_date or since,
            )
        )
        return [row[0] for row in self.env.cr.fetchall()]

    def _reopen_wizard(self) -> dict:
        """Return action to keep the wizard open after running."""
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }
