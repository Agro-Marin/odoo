# Part of Odoo. See LICENSE file for full copyright and licensing details.

import datetime

from odoo import Command, fields
from odoo.tests.common import TransactionCase, new_test_user
from odoo.tools import json as ojson


class TestActivitySystrayPayload(TransactionCase):
    """The To-Do/Task split rebuilds the systray group from raw SQL, so the
    guarantees the base gets from ``search`` have to be re-established here.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(
            cls.env, login="systray_user", groups="base.group_user"
        )
        cls.model_id = cls.env["ir.model"]._get("project.task").id
        cls.activity_type = cls.env.ref("mail.mail_activity_data_todo")

    @classmethod
    def _todo(cls, name, deadline=None, user=None):
        user = user or cls.user
        task = cls.env["project.task"].create(
            {
                "name": name,
                "user_ids": [Command.set(user.ids)],
            }
        )
        cls.env["mail.activity"].create(
            {
                "res_id": task.id,
                "res_model_id": cls.model_id,
                "user_id": user.id,
                "date_deadline": deadline or fields.Date.today(),
                "summary": name,
                "activity_type_id": cls.activity_type.id,
            }
        )
        return task

    def _groups(self, user=None):
        groups = (
            self.env["res.users"].with_user(user or self.user)._get_activity_groups()
        )
        return {g["name"]: g for g in groups if g.get("model") == "project.task"}

    def test_payload_is_json_serialisable(self):
        """A stray Python set does not raise here — json_default stringifies it —
        so the browser silently receives ``"{1, 2, 3}"``. Assert on the encoder
        the response really uses.
        """
        self._todo("serialisable")
        groups = self._groups()
        self.assertTrue(groups)
        for name, group in groups.items():
            with self.subTest(group=name):
                for key, value in group.items():
                    self.assertNotIsInstance(
                        value,
                        set,
                        f"{key} is a set and would ship as its repr",
                    )
                encoded = ojson.scriptsafe.dumps(group)
                self.assertNotIn(
                    "res_ids",
                    encoded,
                    "the id list is only needed to build the domain; nothing on the "
                    "client reads it, and it doubles the payload",
                )

    def test_domain_is_a_list_like_every_other_group(self):
        self._todo("domain shape")
        for group in self._groups().values():
            self.assertIsInstance(group["domain"], list)

    def test_badge_and_the_list_it_opens_agree(self):
        """Including when an activity has been archived: a traversal through
        ``activity_ids`` re-applies that model's active test and drops records
        the badge just counted.
        """
        tasks = [self._todo(f"agree {i}") for i in range(3)]
        self.env["mail.activity"].search([("res_id", "=", tasks[0].id)]).active = False
        self.env.flush_all()
        Task = self.env["project.task"].with_user(self.user)
        for context in ({}, {"active_test": False}):
            with self.subTest(context=context):
                groups = (
                    self.env["res.users"]
                    .with_user(self.user)
                    .with_context(**context)
                    ._get_activity_groups()
                )
                for group in groups:
                    if group.get("model") != "project.task":
                        continue
                    self.assertEqual(
                        group["due_count"],
                        Task.search_count(group["domain"]),
                        "the badge must count exactly what clicking it lists",
                    )

    def test_unreadable_tasks_are_not_counted(self):
        """The base filters through record rules; raw SQL does not."""
        other = new_test_user(self.env, login="systray_other", groups="base.group_user")
        hidden = self._todo("not yours", user=other)
        self.env.flush_all()
        groups = self._groups()
        self.assertFalse(
            groups,
            "an activity on a task this user cannot read must not raise a badge",
        )
        # and the owner does see it
        self.assertEqual(self._groups(user=other)["To-Do"]["due_count"], 1)
        self.assertTrue(hidden.exists())

    def test_systray_limit_is_honoured(self):
        for i in range(5):
            self._todo(f"capped {i}")
        self.env["ir.config_parameter"].sudo().set_param(
            "mail.activity.systray.limit", 2
        )
        self.env.flush_all()
        self.assertEqual(
            self._groups()["To-Do"]["due_count"],
            2,
            "an uncapped systray query is a foot-gun on a long activity backlog",
        )

    def test_split_and_state_buckets(self):
        today = fields.Date.today()
        self._todo("overdue todo", today - datetime.timedelta(days=1))
        self._todo("today todo", today)
        self._todo("planned todo", today + datetime.timedelta(days=1))
        project = self.env["project.project"].create({"name": "Systray project"})
        task = self.env["project.task"].create(
            {
                "name": "real task",
                "project_id": project.id,
                "user_ids": [Command.set(self.user.ids)],
            }
        )
        self.env["mail.activity"].create(
            {
                "res_id": task.id,
                "res_model_id": self.model_id,
                "user_id": self.user.id,
                "date_deadline": today,
                "summary": "real task",
                "activity_type_id": self.activity_type.id,
            }
        )
        self.env.flush_all()
        groups = self._groups()
        self.assertEqual(
            (
                groups["To-Do"]["overdue_count"],
                groups["To-Do"]["today_count"],
                groups["To-Do"]["planned_count"],
                groups["To-Do"]["due_count"],
            ),
            (1, 1, 1, 2),
            "due_count is overdue + today; planned is reported but not badged",
        )
        self.assertEqual(groups["Task"]["today_count"], 1)
        self.assertTrue(groups["To-Do"]["is_todo"])
        self.assertFalse(groups["Task"]["is_todo"])

    def test_group_order_is_stable(self):
        """Both groups carry the same ir.model id, so the client's sort-by-id is
        a tie: the server has to decide the order, not the query planner."""
        self._todo("ordered todo")
        project = self.env["project.project"].create({"name": "Ordered"})
        task = self.env["project.task"].create(
            {
                "name": "ordered task",
                "project_id": project.id,
                "user_ids": [Command.set(self.user.ids)],
            }
        )
        self.env["mail.activity"].create(
            {
                "res_id": task.id,
                "res_model_id": self.model_id,
                "user_id": self.user.id,
                "date_deadline": fields.Date.today(),
                "summary": "ordered task",
                "activity_type_id": self.activity_type.id,
            }
        )
        self.env.flush_all()
        for _ in range(3):
            names = [
                g["name"]
                for g in self.env["res.users"]
                .with_user(self.user)
                ._get_activity_groups()
                if g.get("model") == "project.task"
            ]
            self.assertEqual(names, ["Task", "To-Do"])
