"""Monte Carlo forecasting: the sample it draws from."""

from datetime import timedelta

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .test_project_base import TestProjectCommon


@tagged("post_install", "-at_install")
class TestForecastSampling(TestProjectCommon):
    """A week with no delivery is evidence, not an absent row."""

    def test_zero_delivery_weeks_are_sampled(self) -> None:
        project = self.env["project.project"].create({"name": "Forecast"})
        step = self.env["project.workflow.step"].create(
            {"name": "S", "project_ids": [Command.link(project.id)]}
        )
        now = self.env.cr.now()
        done = self.env["project.task"].create(
            [
                {"name": f"d{i}", "project_id": project.id, "step_id": step.id}
                for i in range(4)
            ]
        )
        done.state = "done"
        self.env["project.task"].create(
            [
                {"name": f"o{i}", "project_id": project.id, "step_id": step.id}
                for i in range(20)
            ]
        )
        self.env.flush_all()
        # Delivery in exactly 2 of the last 12 weeks.
        self.env.cr.execute(
            "UPDATE project_task SET date_closed = %s WHERE id = ANY(%s)",
            (now - timedelta(weeks=1), done[:2].ids),
        )
        self.env.cr.execute(
            "UPDATE project_task SET date_closed = %s WHERE id = ANY(%s)",
            (now - timedelta(weeks=6), done[2:].ids),
        )
        self.env.cr.execute(
            "UPDATE project_project SET create_date = %s WHERE id = %s",
            (now - timedelta(weeks=20), project.id),
        )
        self.env.invalidate_all()

        wizard = self.env["project.forecast.wizard"].create(
            {"project_id": project.id, "weeks_of_history": 12, "simulation_count": 2000}
        )
        sample = wizard._get_weekly_throughput()

        self.assertIn(0, sample, "weeks with no delivery must be sampled")
        self.assertGreaterEqual(len(sample), 12, "every week in the window is a sample")

        wizard.action_run_forecast()
        self.assertGreater(
            len({wizard.p50_weeks, wizard.p85_weeks, wizard.p95_weeks}),
            1,
            "a sample with variance must produce distinct percentiles",
        )
        naive = wizard.remaining_items / (sum(sample) / len(sample))
        self.assertLessEqual(
            wizard.p50_weeks, 2 * naive, "the forecast must not be wildly optimistic"
        )

    def test_backdated_closures_are_not_dropped(self) -> None:
        """The window floor is the earlier of project creation and first
        closure, so imported history still counts."""
        project = self.env["project.project"].create({"name": "Backdated"})
        step = self.env["project.workflow.step"].create(
            {"name": "S", "project_ids": [Command.link(project.id)]}
        )
        now = fields.Datetime.now()
        task = self.env["project.task"].create(
            {"name": "old", "project_id": project.id, "step_id": step.id}
        )
        task.state = "done"
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE project_task SET date_closed = %s WHERE id = %s",
            (now - timedelta(days=10), task.id),
        )
        self.env.invalidate_all()

        wizard = self.env["project.forecast.wizard"].create(
            {"project_id": project.id, "weeks_of_history": 8}
        )
        self.assertEqual(sum(wizard._get_weekly_throughput()), 1)

    def test_forecast_wizard_throughput_by_closure(self) -> None:
        """The forecast wizard's throughput query must run (no INTERVAL syntax
        error), count non-template tasks, and bucket by date_closed."""
        project = self.project_pigs
        now = fields.Datetime.now()
        for i in range(3):
            self.env["project.task"].create(
                {
                    "name": f"done {i}",
                    "project_id": project.id,
                    "state": "done",
                    "date_closed": now - timedelta(days=3),
                }
            )
        wizard = self.env["project.forecast.wizard"].create(
            {"project_id": project.id, "weeks_of_history": 8}
        )
        throughput = wizard._get_weekly_throughput()  # must not raise
        self.assertEqual(sum(throughput), 3)

    def test_forecast_wizard_rejects_non_positive_sims(self) -> None:
        """The Monte Carlo wizard must not IndexError on simulation_count <= 0."""
        wizard = self.env["project.forecast.wizard"].create(
            {
                "project_id": self.project_pigs.id,
                "simulation_count": 0,
            }
        )
        with self.assertRaises(UserError):
            wizard.action_run_forecast()

    def test_forecast_throughput_excludes_canceled(self) -> None:
        """Throughput forecasting must count delivered (done) work only — a
        canceled task is not delivery."""
        now = fields.Datetime.now()
        self.env["project.task"].create(
            {
                "name": "done",
                "project_id": self.project_pigs.id,
                "state": "done",
                "date_closed": now - timedelta(days=3),
            }
        )
        self.env["project.task"].create(
            {
                "name": "canceled",
                "project_id": self.project_pigs.id,
                "state": "canceled",
                "date_closed": now - timedelta(days=3),
            }
        )
        wizard = self.env["project.forecast.wizard"].create(
            {"project_id": self.project_pigs.id, "weeks_of_history": 8}
        )
        self.assertEqual(
            sum(wizard._get_weekly_throughput()),
            1,
            "only the done task counts toward throughput",
        )

    def test_forecast_throughput_enforces_read_access(self) -> None:
        """The raw-SQL throughput query must not leak a project the user cannot
        read (record rules don't apply to raw SQL — an explicit check does)."""
        wizard = self.env["project.forecast.wizard"].create(
            {"project_id": self.project_goats.id, "weeks_of_history": 8}
        )
        # project_goats is follower-only; user_projectuser is not a follower.
        with self.assertRaises(AccessError):
            wizard.with_user(self.user_projectuser)._get_weekly_throughput()
