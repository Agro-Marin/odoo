from odoo.tests import tagged
from odoo.tools import formataddr

from odoo.addons.mail.models.base import _MAIL_REPLY_TO_LENGTH_LIMIT
from odoo.addons.mail.tests.common import MailCommon

FAILURE_TYPE = "mail_email_invalid"


@tagged("mail_notification")
class TestMailNotificationFailureReason(MailCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["res.lang"]._activate_lang("fr_FR")
        cls.env["ir.model.fields.selection"].search(
            [
                ("field_id.model", "=", "mail.notification"),
                ("field_id.name", "=", "failure_type"),
                ("value", "=", FAILURE_TYPE),
            ],
            limit=1,
        ).with_context(lang="fr_FR").name = "Adresse invalide"

    def test_failure_reason_is_translated(self):
        notification = self.env["mail.notification"].new(
            {"failure_type": FAILURE_TYPE, "notification_type": "email"}
        )
        self.assertEqual(
            notification.with_context(lang="fr_FR").format_failure_reason(),
            "Adresse invalide",
            "the label must come from the field's translated selection, not from "
            "its raw `selection` attribute",
        )


@tagged("mail_notification")
class TestReplyToLengthBoundary(MailCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.record = cls.env["res.partner"].create({"name": "Reply-To Boundary"})
        cls.author = cls.env["res.partner"].create({"name": "The Author"})

    def _name_of_exact_length(self, address, length):
        for size in range(1, length):
            name = "A" * size
            if len(formataddr((name, address))) == length:
                return name
        raise ValueError(f"no name gives a {length}-character reply-to for {address}")

    def test_reply_to_at_the_limit_keeps_the_author(self):
        address = "catchall.test@test.mycompany.com"
        self.author.name = self._name_of_exact_length(
            address, _MAIL_REPLY_TO_LENGTH_LIMIT
        )
        formatted = self.record._notify_get_reply_to_formatted_email(
            address, author_id=self.author.id
        )
        self.assertEqual(len(formatted), _MAIL_REPLY_TO_LENGTH_LIMIT)
        self.assertEqual(formatted, formataddr((self.author.name, address)))

    def test_reply_to_over_the_limit_drops_the_name(self):
        address = "catchall.test@test.mycompany.com"
        self.author.name = self._name_of_exact_length(
            address, _MAIL_REPLY_TO_LENGTH_LIMIT + 1
        )
        formatted = self.record._notify_get_reply_to_formatted_email(
            address, author_id=self.author.id
        )
        self.assertLessEqual(len(formatted), _MAIL_REPLY_TO_LENGTH_LIMIT)
        self.assertNotIn(
            self.author.name, formatted, "the over-long author name must not survive"
        )


@tagged("mail_notification")
class TestNotificationKeepsTheAddressUsed(MailCommon):
    """The chatter must report the address a notification was actually sent to,
    not whatever the recipient's contact card says today."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.record = cls.env["res.partner"].create({"name": "Record"})
        cls.customer = cls.env["res.partner"].create(
            {"name": "Customer", "email": "before@test.example.com"}
        )

    def test_partner_notification_records_the_address_used(self):
        with self.mock_mail_gateway():
            self.record.message_notify(
                body="<p>Hello</p>",
                partner_ids=self.customer.ids,
                subject="Hello",
            )
        notification = self.env["mail.notification"].search(
            [
                ("res_partner_id", "=", self.customer.id),
                ("notification_type", "=", "email"),
            ],
            order="id desc",
            limit=1,
        )
        self.assertTrue(notification, "the customer must have been mailed")
        self.assertEqual(notification.mail_email_address, "before@test.example.com")
        self.customer.email = "after@test.example.com"
        self.assertEqual(
            notification.mail_email_address,
            "before@test.example.com",
            "changing the contact must not rewrite what was already sent",
        )
