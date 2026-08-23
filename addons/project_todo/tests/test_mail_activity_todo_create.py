# Part of Odoo. See LICENSE file for full copyright and licensing details.

import datetime

from markupsafe import Markup

from odoo import fields
from odoo.tests.common import TransactionCase


class TestMailActivityTodo(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user_admin = cls.env.ref("base.user_admin")
        cls.mail_activity = cls.env["mail.activity.todo.create"].create(
            {
                "summary": "test_summary",
                "date_deadline": datetime.date.today(),
                "note": Markup("<p>details</p>"),
                "user_id": cls.user_admin.id,
            }
        )
        cls.mail_activity.create_todo_activity()

    def test_create_todo_activity(self):
        todo_1 = self.env["project.task"].search(
            [("name", "ilike", "test_summary")], limit=1
        )
        activity_1 = self.env["mail.activity"].search(
            [("summary", "ilike", "test_summary")], limit=1
        )
        self.assertTrue(todo_1.exists(), "A Todo should have been created")
        self.assertEqual(
            todo_1.description,
            Markup("<p>details</p>"),
            "The Todo description should be the same as the mail.activity.todo.create note",
        )
        self.assertTrue(activity_1.exists(), "An Activity should have been created")
        self.assertEqual(
            activity_1.summary,
            todo_1.name,
            "The Todo and The Activity should have the same name/summary",
        )
        self.assertEqual(
            activity_1.user_id,
            todo_1.user_ids,
            "The Todo and The Activity should have the same user",
        )

    def test_deadline_is_the_day_the_user_picked(self):
        """``date_end`` is a Datetime and the wizard collects a Date.

        Storing the Date as-is means naive UTC midnight, which reads back as the
        *previous* evening anywhere west of UTC — the to-do says "Yesterday" for
        a deadline the user set as today. Assert on what the user is shown, not
        on the stored UTC instant, or the bug passes the test in every timezone.
        """
        picked = datetime.date(2026, 8, 10)
        for tz in ("UTC", "America/Mexico_City", "Pacific/Kiritimati", "Asia/Tokyo"):
            with self.subTest(tz=tz):
                self.user_admin.tz = tz
                wizard = (
                    self.env["mail.activity.todo.create"]
                    .with_user(self.user_admin)
                    .create(
                        {
                            "summary": f"tz {tz}",
                            "date_deadline": picked,
                            "user_id": self.user_admin.id,
                        }
                    )
                )
                wizard.create_todo_activity()
                todo = self.env["project.task"].search(
                    [("name", "=", f"tz {tz}")], limit=1
                )
                # Read it back the way the web client does: an explicit tz in
                # context. Relying on the ambient one would let whatever the
                # test env happens to carry decide the answer.
                shown = fields.Datetime.context_timestamp(
                    todo.with_context(tz=tz), todo.date_end
                ).date()
                self.assertEqual(
                    shown,
                    picked,
                    f"in {tz} the deadline is displayed as {shown}, not the picked {picked}",
                )
                activity = self.env["mail.activity"].search(
                    [("summary", "=", f"tz {tz}")], limit=1
                )
                self.assertEqual(
                    activity.date_deadline,
                    shown,
                    "the to-do and the activity it created must agree on the day",
                )
