# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Regression tests for the seventh mail audit.

Pins the non-obvious correctness/security fixes that lacked a direct test:

* an out-of-office auto-reply triggered by an internal note stays internal;
* the mail-gateway loop detector fires for record-creating routes (thread_id
  is None on the fallback path, not 0);
* a malformed Cc header no longer aborts inbound routing;
* ``_compute_starred`` (rewritten to a scoped SQL query) stays per-user correct.
"""

from email.message import EmailMessage

from odoo.tests import tagged

from odoo.addons.mail.tests.common import MailCommon
from odoo.addons.test_mail.tests.common import TestRecipients


@tagged("post_install", "-at_install")
class TestOutOfOfficeInternalNote(MailCommon, TestRecipients):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.record = cls.env["mail.test.container"].create({"name": "OOO note probe"})

    def test_ooo_reply_to_internal_note_stays_internal(self):
        """An out-of-office reply triggered by an internal note quotes the note
        body; it must be posted internally (mt_note + is_internal) so it is not
        republished as a public comment to portal followers."""
        self._setup_out_of_office(self.user_employee_c2)
        self.assertTrue(self.user_employee_c2.is_out_of_office)
        mt_note = self.env.ref("mail.mt_note")

        with self.mock_mail_gateway(), self.mock_mail_app():
            self.record.with_user(self.user_admin).message_post(
                body="internal note pinging an away teammate",
                message_type="comment",
                partner_ids=self.user_employee_c2.partner_id.ids,
                subtype_id=mt_note.id,
                is_internal=True,
            )
        ooo = (
            self.env["mail.message"]
            .sudo()
            .search(
                [
                    ("model", "=", "mail.test.container"),
                    ("res_id", "=", self.record.id),
                    ("message_type", "=", "out_of_office"),
                ]
            )
        )
        self.assertTrue(ooo, "the OOO auto-reply must still be generated")
        self.assertTrue(
            all(ooo.mapped("is_internal")),
            "OOO reply to an internal note must stay internal",
        )
        self.assertEqual(
            ooo.subtype_id,
            mt_note,
            "OOO reply to an internal note must use mt_note, not mt_comment",
        )


@tagged("post_install", "-at_install")
class TestGatewayLoopDetection(MailCommon):
    def _make_incoming_email(self):
        message = EmailMessage()
        message["Message-Id"] = "<loop-probe@test.example.com>"
        message["From"] = "loop@test.example.com"
        message["To"] = "catchall@test.example.com"
        message["Return-Path"] = "loop@test.example.com"
        message["Subject"] = "loop probe"
        message.set_content("body")
        return message

    def _detect(self, thread_id):
        message = self._make_incoming_email()
        message_dict = {
            "email_from": "loop@test.example.com",
            "to": "catchall@test.example.com",
            "message_id": "<loop-probe@test.example.com>",
            "author_id": False,
        }
        routes = [("mail.test.gateway", thread_id, {}, self.env.uid, None)]
        with self.mock_mail_gateway():
            return self.env["mail.thread"]._detect_loop_sender(
                message, message_dict, routes
            )

    def test_loop_detection_fires_for_none_thread_id(self):
        """Record-creating routes carry a falsy thread_id: 0 for alias routes but
        None for the fallback-model route. `0 in thread_ids` missed None, silently
        disabling loop detection on the standard fetchmail create path."""
        self.env["ir.config_parameter"].sudo().set_param(
            "mail.gateway.loop.threshold", 1
        )
        # seed enough recently-created records to exceed the threshold
        model = self.env["mail.test.gateway"]
        for _i in range(3):
            model.create({"name": "loop", "email_from": "loop@test.example.com"})

        self.assertTrue(
            self._detect(None),
            "a None (fallback-model) record-creating route must trigger loop "
            "detection just like a 0 (alias) route",
        )
        self.assertTrue(self._detect(0), "sanity: the 0 route must also detect")


@tagged("post_install", "-at_install")
class TestCcSanitization(MailCommon):
    def test_malformed_cc_does_not_crash(self):
        """A Cc entry that email_split_tuples accepts but email_normalize rejects
        (e.g. a bare local part) must be skipped, not fed to formataddr where it
        raised AttributeError and aborted the whole inbound route."""
        model = self.env["mail.test.cc"]
        result = model._mail_cc_sanitized_raw_dict(
            'Valid <valid@test.example.com>, "Broken" <a@>, plain@test.example.com'
        )
        self.assertNotIn(False, result)
        self.assertIn("valid@test.example.com", result)
        self.assertIn("plain@test.example.com", result)


@tagged("post_install", "-at_install")
class TestStarredCompute(MailCommon):
    def test_starred_is_per_user(self):
        """The SQL-scoped _compute_starred must report starred only for the
        current user, and not leak another user's star."""
        record = self.env["mail.test.container"].create({"name": "starred probe"})
        message = record.message_post(body="star me", message_type="comment")
        message.with_user(self.user_employee).toggle_message_starred()

        self.assertTrue(
            message.with_user(self.user_employee).starred,
            "the message must be starred for the user who starred it",
        )
        self.assertFalse(
            message.with_user(self.user_admin).starred,
            "the message must not be starred for a different user",
        )
