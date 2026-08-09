"""Monte Carlo forecasting: the sample it draws from."""

from datetime import timedelta

from odoo import Command, fields
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
