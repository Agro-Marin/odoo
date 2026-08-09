"""Archiving and deleting a task takes its sub-tree with it, both ways."""

from odoo.tests import tagged

from .test_project_base import TestProjectCommon


@tagged("post_install", "-at_install")
class TestTaskArchiving(TestProjectCommon):
    def setUp(self) -> None:
        super().setUp()
        self.Task = self.env["project.task"]
        self.parent = self.Task.create(
            {"name": "Parent", "project_id": self.project_pigs.id}
        )
        self.child = self.Task.create(
            {
                "name": "Child",
                "project_id": self.project_pigs.id,
                "parent_id": self.parent.id,
            }
        )
        self.grandchild = self.Task.create(
            {
                "name": "Grandchild",
                "project_id": self.project_pigs.id,
                "parent_id": self.child.id,
            }
        )

    def _exists(self, task) -> bool:
        return bool(self.Task.with_context(active_test=False).browse(task.id).exists())

    def test_archiving_a_parent_archives_its_subtasks(self) -> None:
        self.parent.action_archive()
        self.assertFalse(self.child.with_context(active_test=False).active)
        self.assertFalse(self.grandchild.with_context(active_test=False).active)

    def test_unarchiving_a_parent_restores_its_subtasks(self) -> None:
        """``action_archive`` took the sub-tasks down and ``action_unarchive``
        left them there, so archiving a task and changing your mind lost its
        sub-tasks for good — nothing in the UI shows an archived sub-task, so
        the only way back was an archived filter and one unarchive per row."""
        self.parent.action_archive()
        self.parent.action_unarchive()
        self.assertTrue(self.child.with_context(active_test=False).active)
        self.assertTrue(self.grandchild.with_context(active_test=False).active)

    def test_a_subtask_archived_on_its_own_stays_archived(self) -> None:
        """Only the children the parent took down come back — a sub-task that
        was archived deliberately, and shows in the project on its own
        (``display_in_project``), is not the parent's to restore."""
        standalone = self.Task.create(
            {
                "name": "Standalone",
                "project_id": self.project_pigs.id,
                "parent_id": self.parent.id,
            }
        )
        standalone.display_in_project = True
        standalone.action_archive()
        self.parent.action_archive()
        self.parent.action_unarchive()
        self.assertFalse(standalone.with_context(active_test=False).active)

    def test_deleting_a_parent_deletes_its_archived_subtree(self) -> None:
        """``unlink`` swept in ``_get_all_subtasks()``, whose recursive CTE
        honours ``active_test`` — so archived descendants were left behind, and
        ``parent_id`` has no ``ondelete``, so they survived as archived root
        tasks of the project. Invisible orphans, produced by the most ordinary
        sequence there is: archive a task, unarchive it, delete it."""
        self.child.action_archive()
        child_id, grandchild_id = self.child.id, self.grandchild.id
        self.parent.unlink()

        survivors = self.Task.with_context(active_test=False).browse(
            [child_id, grandchild_id]
        )
        self.assertFalse(
            survivors.exists(),
            "an archived sub-tree must be deleted with its parent, not orphaned",
        )

    def test_deleting_a_parent_deletes_its_active_subtree(self) -> None:
        child_id, grandchild_id = self.child.id, self.grandchild.id
        self.parent.unlink()
        self.assertFalse(
            self.Task.with_context(active_test=False)
            .browse([child_id, grandchild_id])
            .exists()
        )
