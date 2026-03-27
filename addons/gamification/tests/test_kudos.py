from odoo.exceptions import UserError
from odoo.tests import common

from odoo.addons.mail.tests.common import mail_new_test_user


class TestKudos(common.TransactionCase):
    """Tests for peer-to-peer kudos recognition system."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sender = mail_new_test_user(
            cls.env,
            login="kudos_sender",
            name="Kudos Sender",
            email="sender@example.com",
            karma=0,
            groups="base.group_user",
        )
        cls.recipient = mail_new_test_user(
            cls.env,
            login="kudos_recipient",
            name="Kudos Recipient",
            email="recipient@example.com",
            karma=0,
            groups="base.group_user",
        )
        cls.category_teamwork = cls.env.ref("gamification.kudos_category_teamwork")
        cls.category_innovation = cls.env.ref("gamification.kudos_category_innovation")

    def _create_kudos(
        self, sender=None, recipient=None, category=None, message="Great job!"
    ):
        """Helper to create a kudos record."""
        return (
            self.env["gamification.kudos"]
            .with_user(sender or self.sender)
            .create(
                {
                    "sender_id": (sender or self.sender).id,
                    "recipient_id": (recipient or self.recipient).id,
                    "category_id": (category or self.category_teamwork).id,
                    "message": message,
                }
            )
        )

    def test_create_kudos_grants_karma(self):
        """Sending kudos automatically grants karma to the recipient."""
        initial_karma = self.recipient.karma
        expected_karma = self.category_teamwork.karma_granted

        kudos = self._create_kudos()

        self.assertEqual(kudos.karma_granted, expected_karma)
        self.assertEqual(
            self.recipient.karma,
            initial_karma + expected_karma,
            "Recipient should receive karma from kudos category",
        )

    def test_create_kudos_different_categories(self):
        """Different categories grant different karma amounts."""
        initial_karma = self.recipient.karma

        self._create_kudos(category=self.category_teamwork)
        karma_after_teamwork = self.recipient.karma

        self._create_kudos(category=self.category_innovation)
        karma_after_innovation = self.recipient.karma

        self.assertEqual(
            karma_after_teamwork - initial_karma,
            self.category_teamwork.karma_granted,
        )
        self.assertEqual(
            karma_after_innovation - karma_after_teamwork,
            self.category_innovation.karma_granted,
        )

    def test_self_kudos_prevented(self):
        """Users cannot send kudos to themselves."""
        with self.assertRaises(UserError, msg="Self-kudos should be prevented"):
            self.env["gamification.kudos"].with_user(self.sender).create(
                {
                    "sender_id": self.sender.id,
                    "recipient_id": self.sender.id,
                    "category_id": self.category_teamwork.id,
                    "message": "I'm great!",
                }
            )

    def test_kudos_posts_to_mail_thread(self):
        """Kudos creation should post a message to the mail thread."""
        kudos = self._create_kudos()
        messages = kudos.message_ids.filtered(
            lambda m: m.subtype_id == self.env.ref("mail.mt_comment")
        )
        self.assertTrue(messages, "Kudos should post a comment message")

    def test_kudos_summary_computed(self):
        """Summary field is auto-computed from sender/recipient/category."""
        kudos = self._create_kudos()
        self.assertIn(self.sender.name, kudos.summary)
        self.assertIn(self.recipient.name, kudos.summary)
        self.assertIn(self.category_teamwork.name, kudos.summary)

    def test_kudos_zero_karma_category(self):
        """Kudos with 0 karma_granted category should not create tracking."""
        self.category_teamwork.karma_granted = 0
        initial_karma = self.recipient.karma

        kudos = self._create_kudos()

        self.assertEqual(kudos.karma_granted, 0)
        self.assertEqual(self.recipient.karma, initial_karma)

    def test_kudos_category_count(self):
        """Category kudos_count reflects number of kudos in that category."""
        self._create_kudos(category=self.category_teamwork)
        self._create_kudos(category=self.category_teamwork)
        self._create_kudos(category=self.category_innovation)

        self.category_teamwork.invalidate_recordset(["kudos_count"])
        self.category_innovation.invalidate_recordset(["kudos_count"])

        self.assertEqual(self.category_teamwork.kudos_count, 2)
        self.assertEqual(self.category_innovation.kudos_count, 1)
