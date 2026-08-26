from odoo import Command
from odoo.tests import tagged

from .test_project_base import TestProjectCommon


@tagged("post_install", "-at_install")
class TestDigestOpenTasks(TestProjectCommon):
    def test_openness_is_state_not_folded_step(self) -> None:
        project = self.env["project.project"].create({"name": "Digest"})
        Step = self.env["project.workflow.step"]
        open_step = Step.create(
            {"name": "Open", "project_ids": [Command.link(project.id)], "fold": False}
        )
        folded_step = Step.create(
            {"name": "Folded", "project_ids": [Command.link(project.id)], "fold": True}
        )
        Task = self.env["project.task"]
        open_in_folded = Task.create(
            {
                "name": "open state, folded step",
                "project_id": project.id,
                "step_id": folded_step.id,
            }
        )
        done_in_open = Task.create(
            {
                "name": "done state, open step",
                "project_id": project.id,
                "step_id": open_step.id,
                "state": "done",
            }
        )
        self.env.flush_all()

        kpi_domain = [
            ("state", "not in", ["done", "canceled"]),
            ("project_id", "!=", False),
        ]
        counted = Task.search(
            kpi_domain + [("id", "in", (open_in_folded | done_in_open).ids)]
        )

        self.assertIn(open_in_folded, counted, "an open task is open wherever it sits")
        self.assertNotIn(done_in_open, counted, "a done task is not open")

    def test_the_kpi_agrees_with_open_task_count(self) -> None:
        project = self.env["project.project"].create({"name": "Digest agreement"})
        folded_step = self.env["project.workflow.step"].create(
            {"name": "Folded", "project_ids": [Command.link(project.id)], "fold": True}
        )
        Task = self.env["project.task"]
        Task.create({"name": "a", "project_id": project.id, "step_id": folded_step.id})
        Task.create({"name": "b", "project_id": project.id, "state": "done"})
        Task.create({"name": "c", "project_id": project.id})
        self.env.flush_all()

        digest_count = Task.search_count(
            [
                ("state", "not in", ["done", "canceled"]),
                ("project_id", "=", project.id),
            ]
        )
        self.assertEqual(digest_count, project.open_task_count)
