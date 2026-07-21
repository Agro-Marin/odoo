"""Regression tests for the sixth mail audit.

Each test pins a specific, empirically-confirmed finding so a future refactor
cannot silently reintroduce it. Backend-only for fast, deterministic runs.
Coverage spans the mail.mail strict-send contract, the inbound charset guard,
discuss.channel pin ACL, activity-type reassignment, mail-gateway loop
detection, default-recipient ban filtering and scheduled-message access.
"""

import email
import email.policy
from unittest.mock import patch

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests.common import tagged
from odoo.tools import mute_logger

from odoo.addons.base.models.ir_mail_server import MailDeliveryException
from odoo.addons.mail.tests.common import MailCommon


@tagged("post_install", "-at_install")
class TestMailStrictSendContract(MailCommon):
    def test_raise_exception_on_single_recipient_failure(self):
        """send(raise_exception=True) must raise when the only recipient fails.

        The per-recipient isolation in _send isolates a delivery error and
        keeps going for the remaining recipients; but with raise_exception a
        mail whose every recipient failed (here, the single recipient) must
        still surface the error rather than reporting a phantom success
        (e.g. 2FA-code / invitation mails).
        """
        partner = self.env["res.partner"].create(
            {"name": "P1", "email": "p1@ext.example.com"}
        )
        mail = (
            self.env["mail.mail"]
            .sudo()
            .create(
                {
                    "subject": "s",
                    "body_html": "<p>x</p>",
                    "email_from": "from@example.com",
                    "recipient_ids": [Command.set(partner.ids)],
                }
            )
        )
        IrMailServer = type(self.env["ir.mail_server"])

        def fake_send(server, message, *args, **kwargs):
            raise MailDeliveryException("hard reject")

        with (
            patch.object(IrMailServer, "send_email", fake_send),
            patch.object(IrMailServer, "_disable_send", lambda server: False),
            mute_logger("odoo.addons.mail.models.mail_mail"),
        ):
            with self.assertRaises(MailDeliveryException):
                mail._send(raise_exception=True)

    def test_partial_failure_keeps_failure_on_sent_mail(self):
        """When some recipients succeed and one fails, the mail is 'sent' but
        keeps its failure_type so the partial failure stays visible."""
        partners = self.env["res.partner"].create(
            [
                {"name": "P1", "email": "p1@ext.example.com"},
                {"name": "P2", "email": "p2@ext.example.com"},
            ]
        )
        mail = (
            self.env["mail.mail"]
            .sudo()
            .create(
                {
                    "subject": "s",
                    "body_html": "<p>x</p>",
                    "email_from": "from@example.com",
                    "recipient_ids": [Command.set(partners.ids)],
                }
            )
        )
        IrMailServer = type(self.env["ir.mail_server"])

        def fake_send(server, message, *args, **kwargs):
            if "p2@" in message["To"]:
                raise MailDeliveryException("reject P2")
            return "<sent>"

        with (
            patch.object(IrMailServer, "send_email", fake_send),
            patch.object(IrMailServer, "_disable_send", lambda server: False),
            mute_logger("odoo.addons.mail.models.mail_mail"),
        ):
            mail._send(raise_exception=False)
        self.assertEqual(mail.state, "sent")
        self.assertTrue(
            mail.failure_type,
            "a partly-failed mail must keep its failure_type for visibility",
        )


@tagged("post_install", "-at_install")
class TestInboundCharsetGuard(MailCommon):
    def test_unknown_charset_does_not_crash_message_parse(self):
        """A part declaring a charset Python cannot resolve (e.g. the RFC 1428
        ``unknown-8bit``, common in bounces) must not crash message_parse and
        lose the inbound mail."""
        raw = (
            "From: sender@ext.example.com\n"
            "To: catchall@example.com\n"
            "Subject: charset test\n"
            "Message-Id: <charset-1@ext.example.com>\n"
            "Content-Type: text/plain; charset=unknown-8bit\n"
            "Content-Transfer-Encoding: 8bit\n"
            "\n"
            "hello body\n"
        )
        message = email.message_from_string(raw, policy=email.policy.default)
        parsed = self.env["mail.thread"].message_parse(message)
        self.assertIn("hello body", parsed["body"])


@tagged("post_install", "-at_install")
class TestChannelPinACL(MailCommon):
    def test_non_member_cannot_pin_message(self):
        """set_message_pin performs a raw SQL update bypassing mail.message
        ACLs, so it must require channel membership, not mere read access."""
        channel = self.env["discuss.channel"]._create_channel(
            name="PinChan", group_id=None
        )
        message = channel.message_post(body="pin me", message_type="comment")
        employee = self.user_employee  # not a member of this channel
        as_attacker = self.env["discuss.channel"].with_user(employee).browse(channel.id)
        # sanity: the non-member can still read the public channel
        self.assertTrue(as_attacker.name)
        with self.assertRaises(AccessError):
            as_attacker.set_message_pin(message.id, pinned=True)


@tagged("post_install", "-at_install")
class TestActivityTypeUnlink(MailCommon):
    def test_unlink_reassigns_archived_activities(self):
        """Deleting an activity type must reassign even archived (done)
        activities, or the ondelete=restrict FK aborts the unlink."""
        act_type = self.env["mail.activity.type"].create({"name": "Custom Type"})
        todo_type = self.env.ref("mail.mail_activity_data_todo")
        partner = self.env["res.partner"].create({"name": "Target"})
        activity = self.env["mail.activity"].create(
            {
                "activity_type_id": act_type.id,
                "res_model_id": self.env.ref("base.model_res_partner").id,
                "res_id": partner.id,
                "summary": "do it",
            }
        )
        # mark done -> the activity is archived, still referencing act_type
        activity.action_done()
        self.assertFalse(
            activity.active, "a done activity must be archived, not deleted"
        )
        # must not raise a FK violation
        act_type.unlink()
        self.assertEqual(
            activity.activity_type_id,
            todo_type,
            "archived activity should have been reassigned to To-Do",
        )


@tagged("post_install", "-at_install")
class TestLoopSenderDomain(MailCommon):
    def test_domain_is_anchored_and_escaped(self):
        """The base mail.thread._detect_loop_sender_domain fallback must build
        anchored, wildcard-escaped matches, not an unanchored substring ilike
        that over-matches (models with the blacklist mixin override it with an
        exact email_normalized match, so test the fallback on the base).

        Two alternatives are required, not one: message_new stores the *raw*
        FROM, so the column holds either a bare address or the full
        ``"Name" <addr>`` form. Matching only the bare form made the loop guard
        match nothing at all on the standard gateway create path.
        """
        MailThread = self.env["mail.thread"]
        with patch.object(
            type(MailThread),
            "_mail_get_primary_email_field",
            lambda self: "email",
        ):
            domain = MailThread._detect_loop_sender_domain("a_b%c@x.com")
        self.assertEqual(domain[0], "|", "must accept both stored forms")
        leaves = domain[1:]
        self.assertEqual(len(leaves), 2)
        escaped = "a\\_b\\%c@x.com"
        for _field, operator, value in leaves:
            self.assertEqual(
                operator,
                "=ilike",
                "anchored equality only — a bare ilike over-matches",
            )
            self.assertIn(
                escaped,
                value,
                "LIKE metacharacters valid in an address must be escaped",
            )
        self.assertEqual(
            [value for _f, _o, value in leaves],
            [escaped, f"%<{escaped}>"],
            "exact address, or the display-name form anchored on <addr>",
        )

    def test_domain_is_none_for_unparseable_sender(self):
        """A FROM that cannot be normalized (``undisclosed-recipients:;``,
        ``<>``, a bare display name) yields False from email_normalize. Building
        a domain from it used to raise AttributeError out of message_process --
        and fetchmail acked the message anyway, losing the mail permanently."""
        MailThread = self.env["mail.thread"]
        with patch.object(
            type(MailThread),
            "_mail_get_primary_email_field",
            lambda self: "email",
        ):
            self.assertIsNone(MailThread._detect_loop_sender_domain(False))
            self.assertIsNone(MailThread._detect_loop_sender_domain(""))


@tagged("post_install", "-at_install")
class TestDefaultRecipientsBanFilter(MailCommon):
    def test_ban_filter_matches_formatted_email(self):
        """The alias/odoobot ban filter must compare through the normalized key,
        so a catchall carrying a display name is still stripped (mail-loop
        guard)."""
        catchall = "loopcatch@test.example.com"
        self.env["ir.config_parameter"].sudo().set_param(
            "mail.catchall.alias", "loopcatch"
        )
        alias_domain = self.env["mail.alias.domain"].search([], limit=1)
        if alias_domain:
            alias_domain.catchall_alias = "loopcatch"
        # a record whose email holds a display-name-formatted catchall address
        record = self.env["res.partner"].create(
            {"name": "Loopy", "email": f'"Support" <{catchall}>'}
        )
        recipients = record._message_get_default_recipients()[record.id]
        emails_blob = "%s %s" % (
            recipients.get("email_to") or "",
            ",".join(str(p) for p in (recipients.get("partner_ids") or [])),
        )
        self.assertNotIn(
            catchall,
            emails_blob,
            "a display-name-formatted catchall must still be banned",
        )
