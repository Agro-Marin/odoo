from odoo import Command
from odoo.tests import TransactionCase


class TestNotificationTypeOnCreate(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.inbox = cls.env.ref("mail.group_mail_notification_type_inbox")
        cls.group_user = cls.env.ref("base.group_user")

    def _create_user(self, login, group_commands):
        return self.env["res.users"].create(
            {"name": login, "login": login, "group_ids": group_commands}
        )

    def test_the_inbox_group_makes_a_new_user_an_inbox_user(self):
        user = self._create_user(
            "inbox_link",
            [Command.link(self.group_user.id), Command.link(self.inbox.id)],
        )

        self.assertEqual(user.notification_type, "inbox")
        self.assertIn(self.inbox, user.group_ids)

    def test_a_set_command_carrying_the_inbox_group_does_the_same(self):
        user = self._create_user(
            "inbox_set", [Command.set([self.group_user.id, self.inbox.id])]
        )

        self.assertEqual(user.notification_type, "inbox")
        self.assertIn(self.inbox, user.group_ids)

    def test_without_the_inbox_group_a_new_user_is_notified_by_email(self):
        user = self._create_user("email_only", [Command.link(self.group_user.id)])

        self.assertEqual(user.notification_type, "email")
        self.assertNotIn(self.inbox, user.group_ids)

    def test_a_portal_user_never_keeps_the_inbox_group(self):
        portal = self.env.ref("base.group_portal")

        user = self._create_user(
            "portal_inbox", [Command.set([portal.id, self.inbox.id])]
        )

        self.assertEqual(user.notification_type, "email")
        self.assertNotIn(self.inbox, user.group_ids)

    def test_a_copy_of_an_inbox_user_stays_an_inbox_user(self):
        user = self.env["res.users"].create(
            {
                "name": "inbox_source",
                "login": "inbox_source",
                "group_ids": [Command.link(self.group_user.id)],
                "notification_type": "inbox",
            }
        )

        copy = user.copy(default={"login": "inbox_copy"})

        self.assertEqual(copy.notification_type, "inbox")
        self.assertIn(self.inbox, copy.group_ids)
