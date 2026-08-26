import psycopg

from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged
from odoo.tools import mute_logger

from .test_project_base import TestProjectCommon


@tagged("post_install", "-at_install")
class TestTaskTriageLifecycle(TestProjectCommon):
    def setUp(self) -> None:
        super().setUp()
        self.TaskTriage = self.env["project.task.triage"].sudo()
        self.task = self.env["project.task"].create(
            {
                "name": "Triaged",
                "project_id": self.project_pigs.id,
                "user_ids": [Command.set(self.user_projectuser.ids)],
            }
        )

    def _rows(self):
        return self.TaskTriage.search([("task_id", "=", self.task.id)])

    def test_assigning_creates_a_row_per_assignee(self) -> None:
        self.assertEqual(self._rows().user_id, self.user_projectuser)

    def test_reassigning_drops_the_previous_assignee_row(self) -> None:
        self.task.write({"user_ids": [Command.set(self.user_projectmanager.ids)]})

        self.assertEqual(
            self._rows().user_id,
            self.user_projectmanager,
            "the former assignee's triage row must not outlive the assignment",
        )
        self.assertFalse(
            self.task.with_user(self.user_projectuser).personal_triage_id,
            "a user who is off the task has no personal stage on it",
        )

    def test_unassigning_everyone_drops_every_row(self) -> None:
        self.task.write({"user_ids": [Command.clear()]})
        self.assertFalse(self._rows())

    def test_adding_an_assignee_keeps_the_existing_ones(self) -> None:
        self.task.write({"user_ids": [Command.link(self.user_projectmanager.id)]})
        self.assertEqual(
            self._rows().user_id,
            self.user_projectuser + self.user_projectmanager,
        )

    def test_the_bucket_a_user_chose_survives_an_unrelated_reassignment(self) -> None:
        bucket = self.env["project.triage"].search(
            [("user_id", "=", self.user_projectuser.id)], order="sequence desc", limit=1
        )
        self._rows().write({"triage_id": bucket.id})
        self.task.write({"user_ids": [Command.link(self.user_projectmanager.id)]})
        kept = self._rows().filtered(lambda r: r.user_id == self.user_projectuser)
        self.assertEqual(kept.triage_id, bucket)

    @mute_logger("odoo.db.cursor")
    def test_triage_ids_is_not_writable(self) -> None:
        self.assertTrue(self.env["project.task"]._fields["triage_ids"].readonly)
        bucket = self.env["project.triage"].search(
            [("user_id", "=", self.user_projectmanager.id)], limit=1
        )
        other_task = self.env["project.task"].create(
            {"name": "No assignee", "project_id": self.project_pigs.id}
        )
        with self.assertRaises((AccessError, psycopg.errors.NotNullViolation)):
            with self.cr.savepoint():
                other_task.with_user(self.user_projectuser).write(
                    {"triage_ids": [Command.link(bucket.id)]}
                )


@tagged("post_install", "-at_install")
class TestTriageClear(TestProjectCommon):
    def test_clearing_the_personal_triage_takes_effect(self) -> None:
        task = self.env["project.task"].create(
            {
                "name": "Triaged",
                "project_id": self.project_pigs.id,
                "user_ids": [Command.link(self.env.user.id)],
            }
        )
        self.assertTrue(task.triage_id)
        task.write({"triage_id": False})
        self.env.invalidate_all()
        self.assertFalse(task.triage_id)

    def test_personal_triage_search_accepts_scalar(self) -> None:
        result = self.env["project.task"].search(
            [("personal_triage_id", "=", 999999999)]
        )
        self.assertEqual(len(result), 0)

    def test_triage_bucket_must_belong_to_user(self) -> None:
        bucket = self.env["project.triage"].create(
            {"name": "Inbox", "user_id": self.user_projectuser.id}
        )
        with self.assertRaises(ValidationError):
            self.env["project.task.triage"].create(
                {
                    "task_id": self.task_1.id,
                    "user_id": self.user_projectmanager.id,
                    "triage_id": bucket.id,
                }
            )

    def test_triage_user_cannot_edit_another_users_bucket(self) -> None:
        Triage = self.env["project.triage"]
        own = Triage.with_user(self.user_projectuser).create(
            {"name": "Mine", "user_id": self.user_projectuser.id}
        )
        own.write({"name": "Renamed"})
        self.assertEqual(own.name, "Renamed")
        other = Triage.sudo().create(
            {"name": "Other", "user_id": self.user_projectmanager.id}
        )
        with self.assertRaises(AccessError):
            other.with_user(self.user_projectuser).write({"name": "Hijacked"})

    def test_batch_create_populates_triage_for_all_assignees(self) -> None:
        project = self.env["project.project"].create({"name": "TriageBatch"})
        tasks = self.env["project.task"].create(
            [
                {
                    "name": "t1",
                    "project_id": project.id,
                    "user_ids": [(6, 0, self.user_projectuser.ids)],
                },
                {
                    "name": "t2",
                    "project_id": project.id,
                    "user_ids": [(6, 0, self.user_projectmanager.ids)],
                },
            ]
        )
        rows = (
            self.env["project.task.triage"]
            .sudo()
            .search([("task_id", "in", tasks.ids)])
        )
        self.assertEqual(len(rows), 2, "each assignee gets a triage row")
        self.assertTrue(
            all(row.triage_id for row in rows),
            "every triage row must get a default bucket",
        )
