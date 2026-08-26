from odoo.fields import Command
from odoo.tests import tagged

from odoo.addons.project.tests.test_project_base import TestProjectCommon


@tagged("-at_install", "post_install")
class TestTaskState(TestProjectCommon):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()

        cls.project_goats.write(
            {
                "allow_dependencies": True,
            }
        )
        (cls.task_1 + cls.task_2).write(
            {
                "project_id": cls.project_goats.id,
            }
        )

    def test_base_state(self) -> None:
        self.assertEqual(
            self.task_1.state,
            "in_progress",
            "The task_1 should be in progress by default",
        )
        self.assertEqual(
            self.task_2.state,
            "in_progress",
            "The task_2 should be in progress by default",
        )

        self.task_1.write(
            {
                "predecessor_ids": [Command.link(self.task_2.id)],
            }
        )
        self.assertEqual(
            self.task_1.state,
            "blocked",
            "The task_1 should be in waiting_normal after depending on another open task",
        )

        self.task_1.write(
            {
                "state": "done",
            }
        )
        self.assertEqual(
            self.task_1.state,
            "done",
            "The task_1 should be in done even if it has a depending task not closed",
        )

        self.task_1.write(
            {
                "state": "in_progress",
            }
        )
        self.assertEqual(
            self.task_1.state,
            "blocked",
            "task_1 state should automatically switch back to waiting_normal because of the task2 dependency",
        )

        self.task_2.write(
            {
                "state": "canceled",
            }
        )
        self.assertEqual(
            self.task_1.state,
            "in_progress",
            "task_1 state should automatically switch back to in_progress when its dependency closes",
        )

    def test_change_stage_or_project(self) -> None:
        stage_won = self.env["project.workflow.step"].search([("name", "=", "Won")])
        project_pigs = self.env["project.project"].search([("name", "=", "Pigs")])

        self.task_1.write(
            {
                "state": "changes_requested",
            }
        )
        self.task_2.write(
            {
                "state": "canceled",
            }
        )
        (self.task_1 + self.task_2).write(
            {
                "step_id": stage_won.id,
            }
        )
        self.assertEqual(
            self.task_1.state,
            "in_progress",
            "task_1 state should automatically switch back to in_progress when its stage changes",
        )
        self.assertEqual(
            self.task_2.state,
            "canceled",
            "task_2 state should stay in its closed state",
        )

        self.task_1.write(
            {
                "state": "changes_requested",
            }
        )

        (self.task_1 + self.task_2).write({"project_id": project_pigs.id})
        self.task_1._onchange_project_id()
        self.assertEqual(
            self.task_1.state,
            "in_progress",
            "task_1 state should automatically switch back to in_progress when its project changes",
        )
        self.assertEqual(
            self.task_2.state,
            "canceled",
            "task_2 state should remain canceled when its project changes",
        )

    def test_duplicate_dependent_task(self) -> None:
        self.task_1.write(
            {
                "predecessor_ids": [Command.link(self.task_2.id)],
            }
        )
        self.assertEqual(
            self.task_1.state,
            "blocked",
            "The task_1 should be in waiting_normal after depending on another open task",
        )

        self.task_1_copy = self.task_1.copy()
        self.assertEqual(
            self.task_1.state,
            "blocked",
            "The task_1_copy should keep his dependence and stay in waiting_normal",
        )

        self.task_2.write(
            {
                "state": "approved",
            }
        )
        self.task_2_copy = self.task_2.copy()
        self.assertEqual(
            self.task_2_copy.state,
            "todo",
            "A copy is a new task: it must start where a freshly created task "
            "starts (the 'todo' default) rather than inheriting a review "
            "verdict or landing on a different state than create() gives.",
        )

        self.task_2.write(
            {
                "state": "done",
            }
        )
        self.assertEqual(
            self.task_1.state,
            "blocked",
            "The task_1 should have both tasks as dependencies and so should stay in waiting when one of the two is completed",
        )
        self.assertEqual(
            self.task_1_copy.state,
            "blocked",
            "The task_1_copy should have both tasks as dependencies and so should stay in waiting when one of the two is completed",
        )

        self.task_2_copy.write(
            {
                "state": "done",
            }
        )

        self.assertEqual(
            self.task_1.state,
            "in_progress",
            "The task_1 should have both tasks as dependencies and so should stay go to 'done' when both dependencies are completed",
        )
        self.assertEqual(
            self.task_1_copy.state,
            "in_progress",
            "The task_1_copy should have both tasks as dependencies and so should stay go to 'done' when both dependencies are completed",
        )

    def test_duplicate_task_state_retention_with_closed_dependencies(
        self,
    ) -> None:
        self.project_pigs.allow_dependencies = True
        self.task_1.predecessor_ids = self.task_2
        self.task_2.write({"state": "done"})
        self.task_1.write({"state": "approved"})

        task_1_copy = self.task_1.copy()

        self.assertEqual(
            self.task_1.state,
            "approved",
            "The task_1 should retain its state after being copied.",
        )
        self.assertEqual(
            task_1_copy.state,
            "todo",
            "A copy must not inherit the original's 'approved' verdict, and "
            "starts on the same default as any newly created task.",
        )

    def test_duplicate_task_state_retention_with_open_dependencies(
        self,
    ) -> None:
        self.project_pigs.allow_dependencies = True
        self.task_1.predecessor_ids = self.task_2
        self.task_2.write({"state": "in_progress"})

        task_1_copy = self.task_1.copy()

        self.assertEqual(self.task_1.state, "blocked")
        self.assertEqual(task_1_copy.state, "blocked")

    def test_task_created_in_waiting_stage_gets_in_progress_state(self) -> None:
        project_pigs = self.env["project.project"].search([("name", "=", "Pigs")])
        task = (
            self.env["project.task"]
            .with_context(
                {
                    "default_state": "blocked",
                }
            )
            .create(
                {
                    "name": "Task initially waiting state",
                    "project_id": project_pigs.id,
                }
            )
        )

        self.assertEqual(task.state, "in_progress", "The task should be in progress")

    def test_changing_parent_do_not_reset_task_state(self) -> None:
        self.task_2.state = "blocked"
        self.task_2.parent_id = self.task_1
        self.assertEqual(
            self.task_2.state,
            "blocked",
            "Changing the task's parent should not reset the task's state.",
        )

    def test_state_dont_reset_when_enabling_task_dependencies(self) -> None:
        self.project_goats.allow_dependencies = False
        self.env.user.group_ids -= self.env.ref(
            "project.group_project_task_dependencies"
        )
        self.task_1.state = "approved"
        self.task_2.state = "changes_requested"
        self.project_goats.allow_dependencies = True
        self.env.user.group_ids += self.env.ref(
            "project.group_project_task_dependencies"
        )
        self.assertEqual(self.task_1.state, "approved")
        self.assertEqual(self.task_2.state, "changes_requested")

    def test_recompute_state_when_task_dependencies_feature_changes(
        self,
    ) -> None:
        self.assertTrue(self.project_goats.allow_dependencies)
        self.assertTrue(
            self.env.user.has_group("project.group_project_task_dependencies")
        )
        self.task_1.predecessor_ids = self.task_2
        self.assertEqual(self.task_1.state, "blocked")
        self.project_goats.allow_dependencies = False
        self.assertEqual(self.task_1.state, "in_progress")
        self.project_goats.allow_dependencies = True
        self.assertEqual(self.task_1.state, "blocked")
        self.task_2.state = "done"
        self.assertEqual(self.task_1.state, "in_progress")
        self.task_1.state = "approved"
        self.project_goats.allow_dependencies = False
        self.assertEqual(self.task_1.state, "approved")
        self.project_goats.allow_dependencies = True
        self.assertEqual(self.task_1.state, "approved")
