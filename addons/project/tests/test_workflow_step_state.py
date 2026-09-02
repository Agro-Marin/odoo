from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestProjectWorkflowStepState(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env["project.project"].create(
            {
                "name": "Test Project",
                "allow_dependencies": True,
            }
        )

        cls.step_new = cls.env["project.workflow.step"].create(
            {
                "name": "New",
                "sequence": 1,
            }
        )
        cls.step_in_progress = cls.env["project.workflow.step"].create(
            {
                "name": "In Progress",
                "sequence": 2,
                "task_state": "in_progress",
            }
        )
        cls.step_done = cls.env["project.workflow.step"].create(
            {
                "name": "Done",
                "sequence": 3,
                "task_state": "done",
            }
        )
        cls.step_canceled = cls.env["project.workflow.step"].create(
            {
                "name": "Canceled",
                "sequence": 4,
                "task_state": "canceled",
            }
        )
        cls.step_todo = cls.env["project.workflow.step"].create(
            {
                "name": "Backlog",
                "sequence": 0,
                "task_state": "todo",
            }
        )

        cls.task = cls.env["project.task"].create(
            {
                "name": "Test task",
                "project_id": cls.project.id,
                "step_id": cls.step_new.id,
                "state": "in_progress",
            }
        )

    def test_task_state_is_set_when_step_has_task_state(self):
        self.task.write({"step_id": self.step_done.id})
        self.assertEqual(self.task.state, "done")
        self.task.write({"step_id": self.step_canceled.id})
        self.assertEqual(self.task.state, "canceled")
        self.task.write({"step_id": self.step_in_progress.id})
        self.assertEqual(self.task.state, "in_progress")

    def test_task_states_dynamic_selection(self):
        expected_states = dict(
            self.env["project.task"].fields_get(allfields=["state"])["state"][
                "selection"
            ]
        )
        self.assertIn(self.step_done.task_state, expected_states)
        self.assertIn(self.step_in_progress.task_state, expected_states)
        self.assertIn(self.step_canceled.task_state, expected_states)

    def test_get_task_states(self):
        task_states = self.step_done._get_task_states()
        expected_states = dict(
            self.env["project.task"].fields_get(allfields=["state"])["state"][
                "selection"
            ]
        )
        task_state_keys = [key for key, _ in task_states]
        self.assertEqual(len(task_state_keys), len(expected_states))
        for state_key in task_state_keys:
            self.assertIn(state_key, expected_states)

    def test_task_state_is_none(self):
        self.step_in_progress.write({"task_state": None})
        self.task.write({"step_id": self.step_in_progress.id})
        self.assertEqual(self.task.state, "in_progress")

    def test_get_task_states_edge_cases(self):
        selection = [("edge_case_1", "Edge Case 1"), ("edge_case_2", "Edge Case 2")]
        with patch.object(
            self.env["project.task"]._fields["state"],
            "_description_selection",
            return_value=selection,
        ):
            task_states = self.step_done._get_task_states()
        self.assertEqual(task_states, selection)

    def test_todo_state_from_step(self):
        self.task.write({"step_id": self.step_todo.id})
        self.assertEqual(self.task.state, "todo")

    def test_compute_state_respects_step_task_state(self):
        self.task.write({"step_id": self.step_todo.id})
        self.assertEqual(self.task.state, "todo")
        self.task.invalidate_recordset(["state"])
        self.assertEqual(self.task.state, "todo")

    def test_dependency_blocking_overrides_step_state(self):
        blocker = self.env["project.task"].create(
            {
                "name": "Blocker task",
                "project_id": self.project.id,
                "step_id": self.step_in_progress.id,
                "state": "in_progress",
            }
        )
        self.task.write(
            {
                "step_id": self.step_todo.id,
                "predecessor_ids": [(4, blocker.id)],
            }
        )
        self.assertEqual(self.task.state, "blocked")

    def test_empty_task_state_fallback(self):
        self.task.write({"step_id": self.step_new.id})
        self.assertEqual(self.task.state, "in_progress")

    def test_closed_state_preserved(self):
        self.task.write({"step_id": self.step_done.id})
        self.assertEqual(self.task.state, "done")
        blocker = self.env["project.task"].create(
            {
                "name": "Blocker task",
                "project_id": self.project.id,
                "step_id": self.step_in_progress.id,
                "state": "in_progress",
            }
        )
        self.task.write({"predecessor_ids": [(4, blocker.id)]})
        self.assertEqual(self.task.state, "done")

    def test_task_state_constrains_rejects_invalid_key(self):
        self.step_todo.task_state = "todo"
        with patch.object(
            type(self.env["project.workflow.step"]),
            "_get_task_states",
            return_value=[("in_progress", "In Progress")],
        ):
            with self.assertRaises(ValidationError):
                self.step_todo.write({"task_state": "todo"})

    def test_todo_state_in_selection(self):
        states = dict(
            self.env["project.task"].fields_get(allfields=["state"])["state"][
                "selection"
            ]
        )
        self.assertIn("todo", states)
        self.assertEqual(states["todo"], "To Do")
