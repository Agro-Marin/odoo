from datetime import datetime

from odoo import Command
from odoo.tests import freeze_time, tagged

from .test_project_base import TestProjectCommon


@tagged("post_install", "-at_install")
class TestBurnupClosureHistory(TestProjectCommon):
    def test_burnup_flips_at_the_closure_not_at_the_last_step_move(self) -> None:
        year = datetime.now().year - 1
        project = self.env["project.project"].create({"name": "Burnup"})
        alpha, beta = self.env["project.workflow.step"].create(
            [
                {"name": n, "project_ids": [Command.link(project.id)]}
                for n in ("Alpha", "Beta")
            ]
        )
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE project_workflow_step SET create_date = %s WHERE id = ANY(%s)",
            (datetime(year, 1, 1), (alpha + beta).ids),
        )
        with freeze_time(f"{year}-01-10"):
            task = self.env["project.task"].create(
                {"name": "hist", "project_id": project.id, "step_id": alpha.id}
            )
            self.env.flush_all()
            self.env.cr.precommit.run()
        self.env.cr.execute(
            "UPDATE project_task SET create_date = %s WHERE id = %s",
            (datetime(year, 1, 10), task.id),
        )
        with freeze_time(f"{year}-02-10"):
            task.state = "done"
            self.env.flush_all()
            self.env.cr.precommit.run()
        with freeze_time(f"{year}-03-10"):
            task.step_id = beta
            self.env.flush_all()
            self.env.cr.precommit.run()
        self.env.invalidate_all()

        rows = self.env["project.task.burndown.chart.report"]._read_group(
            [("project_id", "=", project.id)], ["date:month", "is_closed"], ["__count"]
        )
        open_months = sorted(
            str(date)[:7] for date, closed, _count in rows if closed == "open"
        )
        self.assertEqual(
            open_months,
            [f"{year}-01"],
            "only the month before the closure may read as open",
        )
