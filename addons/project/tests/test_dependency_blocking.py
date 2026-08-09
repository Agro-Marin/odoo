"""Predecessors block a task from the moment it is created."""

from odoo import Command
from odoo.tests import tagged

from .test_project_base import TestProjectCommon


@tagged("post_install", "-at_install")
class TestPredecessorBlockAtCreate(TestProjectCommon):
    """A dependency given at create time blocks the task, like one given later."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.project_pigs.allow_dependencies = True

    def _predecessor(self):
        return self.env["project.task"].create(
            {"name": "Predecessor", "project_id": self.project_pigs.id}
        )

    def test_blocked_when_predecessor_given_at_create(self) -> None:
        """``state`` carries a default, so the ORM writes ``todo`` straight to
        the row and ``_compute_state`` is never invoked — instrumented at zero
        calls. The record stored ``todo`` while ``is_blocked_by_predecessors()``
        answered True."""
        predecessor = self._predecessor()
        task = self.env["project.task"].create(
            {
                "name": "Successor",
                "project_id": self.project_pigs.id,
                "predecessor_ids": [Command.link(predecessor.id)],
            }
        )
        self.assertTrue(task.is_blocked_by_predecessors())
        self.assertEqual(task.state, "blocked")

    def test_blocked_with_command_set(self) -> None:
        predecessor = self._predecessor()
        task = self.env["project.task"].create(
            {
                "name": "Successor",
                "project_id": self.project_pigs.id,
                "predecessor_ids": [Command.set([predecessor.id])],
            }
        )
        self.assertEqual(task.state, "blocked")

    def test_blocked_through_the_import_path(self) -> None:
        """The spreadsheet import is the path that actually suffered: a batch of
        dependent tasks all landed unblocked."""
        predecessor = self._predecessor()
        self.env["ir.model.data"].create(
            [
                {
                    "module": "__test_batch_e__",
                    "name": "project",
                    "model": "project.project",
                    "res_id": self.project_pigs.id,
                },
                {
                    "module": "__test_batch_e__",
                    "name": "predecessor",
                    "model": "project.task",
                    "res_id": predecessor.id,
                },
            ]
        )
        result = self.env["project.task"].load(
            ["name", "project_id/id", "predecessor_ids/id"],
            [
                [
                    "Imported successor",
                    "__test_batch_e__.project",
                    "__test_batch_e__.predecessor",
                ]
            ],
        )
        self.assertFalse(
            [m for m in result["messages"] if m.get("type") == "error"],
            result["messages"],
        )
        imported = self.env["project.task"].browse(result["ids"])
        self.assertEqual(imported.state, "blocked")

    def test_closed_task_is_not_reopened_into_blocked(self) -> None:
        predecessor = self._predecessor()
        task = self.env["project.task"].create(
            {
                "name": "Already done",
                "project_id": self.project_pigs.id,
                "state": "done",
                "predecessor_ids": [Command.link(predecessor.id)],
            }
        )
        self.assertEqual(task.state, "done")

    def test_not_blocked_when_the_feature_is_off(self) -> None:
        self.project_pigs.allow_dependencies = False
        predecessor = self._predecessor()
        task = self.env["project.task"].create(
            {
                "name": "Successor",
                "project_id": self.project_pigs.id,
                "predecessor_ids": [Command.link(predecessor.id)],
            }
        )
        self.assertNotEqual(task.state, "blocked")
