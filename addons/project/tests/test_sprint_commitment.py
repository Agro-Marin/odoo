from odoo import Command
from odoo.tests import tagged

from .test_project_base import TestProjectCommon


@tagged("post_install", "-at_install")
class TestSprintCommitmentHistory(TestProjectCommon):
    def test_closed_sprint_does_not_report_full_completion(self) -> None:
        project = self.env["project.project"].create(
            {"name": "Sprints", "use_sprints": True}
        )
        step = self.env["project.workflow.step"].create(
            {"name": "S", "project_ids": [Command.link(project.id)]}
        )
        sprint = self.env["project.sprint"].create(
            {
                "name": "S1",
                "project_id": project.id,
                "date_start": "2026-08-03",
                "date_end": "2026-08-14",
            }
        )
        done, todo = self.env["project.task"].create(
            [
                {
                    "name": name,
                    "project_id": project.id,
                    "step_id": step.id,
                    "sprint_id": sprint.id,
                    "story_points": 3.0,
                }
                for name in ("delivered", "carried")
            ]
        )
        done.state = "done"
        sprint.invalidate_recordset()
        self.assertEqual(sprint.task_count, 2)
        self.assertEqual(sprint.completion_pct, 50.0)

        sprint.action_close()
        sprint.invalidate_recordset()

        self.assertFalse(todo.sprint_id, "unfinished work returns to the backlog")
        self.assertEqual(sprint.carried_over_count, 1)
        self.assertEqual(sprint.carried_over_story_points, 3.0)
        self.assertEqual(
            sprint.task_count, 2, "the sprint still knows what it committed to"
        )
        self.assertEqual(sprint.completed_count, 1)
        self.assertEqual(sprint.completion_pct, 50.0, "not 100%")
        self.assertEqual(sprint.story_points_committed, 6.0)
        self.assertEqual(sprint.story_points_completed, 3.0)
