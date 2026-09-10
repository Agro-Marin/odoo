from odoo.tests import TransactionCase


class TestTaskStateOnCreate(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env["project.project"].create({"name": "Project"})
        cls.step = cls.project.workflow_step_ids[:1]

    def test_the_step_task_state_sets_the_state_of_a_new_task(self):
        self.step.task_state = "in_progress"

        task = self.env["project.task"].create(
            {"name": "Task", "project_id": self.project.id, "step_id": self.step.id}
        )

        self.assertEqual(task.state, "in_progress")

    def test_an_explicit_state_wins_over_the_step(self):
        self.step.task_state = "in_progress"

        task = self.env["project.task"].create(
            {
                "name": "Task",
                "project_id": self.project.id,
                "step_id": self.step.id,
                "state": "approved",
            }
        )

        self.assertEqual(task.state, "approved")

    def test_a_step_without_a_task_state_leaves_the_task_to_do(self):
        self.step.task_state = False

        task = self.env["project.task"].create(
            {"name": "Task", "project_id": self.project.id, "step_id": self.step.id}
        )

        self.assertEqual(task.state, "todo")
