import datetime

from odoo import fields
from odoo.tests.common import TransactionCase


class TestActivitySystrayCounter(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.test_user = cls.env["res.users"].create(
            {
                "name": "Test User",
                "login": "testuser",
            }
        )
        cls.test_project = cls.env["project.project"].create(
            {
                "name": "Test Project",
            }
        )

        cls._create_task_scenarios(is_todo=False)
        cls._create_task_scenarios(is_todo=True)

    @classmethod
    def _create_task_scenarios(cls, is_todo=False):
        today = fields.Date.today()
        yesterday = today - datetime.timedelta(days=1)
        tomorrow = today + datetime.timedelta(days=1)

        task_details = {"user_ids": [(6, 0, [cls.test_user.id])]}
        if not is_todo:
            task_details["project_id"] = cls.test_project.id

        name_prefix = "To-Do" if is_todo else "Task"

        record_overdue = cls.env["project.task"].create(
            {**task_details, "name": f"{name_prefix} Overdue Record"}
        )
        cls.env["mail.activity"].create(
            [
                {
                    "res_id": record_overdue.id,
                    "res_model_id": cls.env.ref("project.model_project_task").id,
                    "user_id": cls.test_user.id,
                    "date_deadline": yesterday,
                    "summary": "Overdue 1",
                },
                {
                    "res_id": record_overdue.id,
                    "res_model_id": cls.env.ref("project.model_project_task").id,
                    "user_id": cls.test_user.id,
                    "date_deadline": yesterday,
                    "summary": "Overdue 2",
                },
            ]
        )

        record_today = cls.env["project.task"].create(
            {**task_details, "name": f"{name_prefix} Today Record"}
        )
        cls.env["mail.activity"].create(
            [
                {
                    "res_id": record_today.id,
                    "res_model_id": cls.env.ref("project.model_project_task").id,
                    "user_id": cls.test_user.id,
                    "date_deadline": today,
                    "summary": "Today Activity",
                },
                {
                    "res_id": record_today.id,
                    "res_model_id": cls.env.ref("project.model_project_task").id,
                    "user_id": cls.test_user.id,
                    "date_deadline": tomorrow,
                    "summary": "Planned Activity",
                },
            ]
        )

        record_planned = cls.env["project.task"].create(
            {**task_details, "name": f"{name_prefix} Planned Record"}
        )
        cls.env["mail.activity"].create(
            {
                "res_id": record_planned.id,
                "res_model_id": cls.env.ref("project.model_project_task").id,
                "user_id": cls.test_user.id,
                "date_deadline": tomorrow,
                "summary": "Planned",
            }
        )

    def test_systray_task_and_todo_split(self):
        activity_groups = (
            self.env["res.users"].with_user(self.test_user)._get_activity_groups()
        )

        task_group = next((g for g in activity_groups if g.get("name") == "Task"), None)
        todo_group = next(
            (g for g in activity_groups if g.get("name") == "To-Do"), None
        )

        self.assertTrue(task_group)
        self.assertTrue(todo_group)

        self.assertEqual(task_group["overdue_count"], 1)
        self.assertEqual(task_group["today_count"], 1)
        self.assertEqual(task_group["planned_count"], 1)
        self.assertEqual(
            task_group["due_count"], 2, "Task due_count should be: overdue + today"
        )

        self.assertEqual(todo_group["overdue_count"], 1)
        self.assertEqual(todo_group["today_count"], 1)
        self.assertEqual(todo_group["planned_count"], 1)
        self.assertEqual(
            todo_group["due_count"], 2, "To-Do due_count should be: overdue + today"
        )
