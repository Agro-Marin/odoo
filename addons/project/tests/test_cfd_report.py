from datetime import datetime

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import freeze_time, tagged

from .test_project_base import TestProjectCommon


@tagged("post_install", "-at_install")
class TestCfdReport(TestProjectCommon):
    def test_cfd_reconstructs_step_history(self) -> None:
        year = datetime.now().year - 1
        project = self.env["project.project"].create({"name": "CFD"})
        alpha, beta = self.env["project.workflow.step"].create(
            [
                {"name": n, "sequence": i, "project_ids": [Command.link(project.id)]}
                for i, n in enumerate(("Alpha", "Beta"), start=1)
            ]
        )
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE project_workflow_step SET create_date = %s WHERE id = ANY(%s)",
            (datetime(year, 1, 1), (alpha + beta).ids),
        )
        with freeze_time(f"{year}-01-10"):
            task = self.env["project.task"].create(
                {"name": "flow", "project_id": project.id, "step_id": alpha.id}
            )
            self.env.flush_all()
            self.env.cr.precommit.run()
        self.env.cr.execute(
            "UPDATE project_task SET create_date = %s WHERE id = %s",
            (datetime(year, 1, 10), task.id),
        )
        with freeze_time(f"{year}-03-10"):
            task.step_id = beta
            self.env.flush_all()
            self.env.cr.precommit.run()
        self.env.invalidate_all()

        rows = self.env["project.cfd.report"]._read_group(
            [("project_id", "=", project.id)],
            ["date:month", "step_id"],
            ["task_count:sum"],
        )
        per_month = {(str(date)[:7], step.name): count for date, step, count in rows}
        self.assertEqual(
            per_month.get((f"{year}-01", "Alpha")),
            1,
            "the task sat in Alpha in January",
        )
        self.assertEqual(
            per_month.get((f"{year}-03", "Beta")),
            1,
            "and moved to Beta in March",
        )
        self.assertNotIn(
            (f"{year}-03", "Alpha"), per_month, "it is no longer counted in Alpha"
        )

    def test_cfd_requires_date_and_step_groupby(self) -> None:
        with self.assertRaises(UserError):
            self.env["project.cfd.report"]._read_group([], ["step_id"], ["__count"])
