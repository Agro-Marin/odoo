"""Regression tests for the fourth mail hardening audit.

Each test pins a specific bug found in the audit so a future refactor cannot
silently reintroduce it. Backend-only (no browser) for fast, deterministic runs.
The findings span models/mail_thread, mail_message, mail_mail, mail_notification,
mail_message_schedule, discuss, fetchmail and tools/web_push.
"""

from unittest.mock import patch

import requests
from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.mail.tests.common import MailCommon
from odoo.addons.mail.tools import web_push


@tagged("post_install", "-at_install")
class TestWebPushSSRF(TransactionCase):
    def test_push_to_end_point_refuses_internal_targets(self):
        """The push endpoint is attacker-controlled (any user registers their
        own device) and POSTed to under sudo by the cron: it must be refused
        when it targets a non-public host, exactly like the link-preview fetch.
        """
        session = requests.Session()
        for endpoint in (
            "http://127.0.0.1/wpush",
            "http://169.254.169.254/latest/meta-data/",  # cloud metadata
            "http://[::1]/wpush",
            "http://10.0.0.1/wpush",
        ):
            with self.assertRaises(
                web_push.DeviceUnreachableError, msg=f"{endpoint} must be refused"
            ):
                # The SSRF guard fires before the payload/keys are used, so a
                # minimal device dict is enough to reach it.
                web_push.push_to_end_point(
                    "https://example.com",
                    {"endpoint": endpoint, "keys": {}},
                    "payload",
                    "priv",
                    "pub",
                    session,
                )


@tagged("post_install", "-at_install")
class TestNeedactionFlush(MailCommon):
    def test_needaction_counter_sees_pending_notification(self):
        """``_compute_message_needaction`` reads mail_notification in raw SQL
        with no @api.depends, so it must flush the model first or an
        in-transaction (not-yet-flushed) notification is invisible.
        """
        record = self.env["res.partner"].create({"name": "Needaction Tgt"})
        message = record.message_post(
            body="hi", message_type="comment", subtype_xmlid="mail.mt_note"
        )
        # Buffered (unflushed) inbox notification for the current user.
        self.env["mail.notification"].create(
            {
                "mail_message_id": message.id,
                "res_partner_id": self.env.user.partner_id.id,
                "notification_type": "inbox",
                "is_read": False,
            }
        )
        record.invalidate_recordset(
            ["message_needaction_counter", "message_needaction"]
        )
        self.assertEqual(record.message_needaction_counter, 1)
        self.assertTrue(record.message_needaction)

    def test_has_error_counter_sees_pending_notification(self):
        """Same missing-flush class of bug for ``_compute_message_has_error``."""
        record = self.env["res.partner"].create({"name": "HasError Tgt"})
        message = record.message_post(
            body="hi", message_type="comment", subtype_xmlid="mail.mt_note"
        )
        self.env["mail.notification"].create(
            {
                "mail_message_id": message.id,
                "author_id": self.env.user.partner_id.id,
                "res_partner_id": self.env.user.partner_id.id,
                "notification_type": "email",
                "notification_status": "exception",
            }
        )
        record.invalidate_recordset(
            ["message_has_error_counter", "message_has_error"]
        )
        self.assertEqual(record.message_has_error_counter, 1)
        self.assertTrue(record.message_has_error)


@tagged("post_install", "-at_install")
class TestBounceEmailNormalized(MailCommon):
    def test_bounce_partner_email_is_normalized(self):
        """When the bounced recipient is recovered from the parent message's
        notification (no Final-Recipient in the DSN), ``bounced_email`` must be
        normalized: it feeds equality searches on ``email_normalized`` in
        ``_routing_handle_bounce``, which a raw mixed-case ``partner.email``
        would silently miss.
        """
        partner = self.env["res.partner"].create(
            {"name": "Bouncer", "email": "Foo@Bar.COM"}
        )
        self.assertEqual(partner.email_normalized, "foo@bar.com")
        message = self.env["mail.message"].create(
            {
                "message_id": "<MYMSGID@example.com>",
                "model": "res.partner",
                "res_id": partner.id,
                "message_type": "email",
                "body": "original",
            }
        )
        self.env["mail.notification"].create(
            {
                "mail_message_id": message.id,
                "res_partner_id": partner.id,
                "notification_type": "email",
                "notification_status": "sent",
            }
        )
        raw = (
            b"From: MAILER-DAEMON@example.com\r\n"
            b"To: bounce@example.com\r\n"
            b"Subject: Delivery Status Notification (Failure)\r\n"
            b'Content-Type: multipart/report; report-type=delivery-status;'
            b' boundary="b"\r\n'
            b"MIME-Version: 1.0\r\n"
            b"\r\n"
            b"--b\r\n"
            b"Content-Type: message/delivery-status\r\n"
            b"\r\n"
            b"Reporting-MTA: dns; example.com\r\n"  # no Final-Recipient
            b"\r\n"
            b"--b\r\n"
            b"Content-Type: message/rfc822\r\n"
            b"\r\n"
            b"Message-Id: <MYMSGID@example.com>\r\n"
            b"From: sender@example.com\r\n"
            b"To: foo@bar.com\r\n"
            b"Subject: original\r\n"
            b"\r\n"
            b"original body\r\n"
            b"--b--\r\n"
        )
        import email
        import email.policy

        email_message = email.message_from_bytes(raw, policy=email.policy.SMTP)
        message_dict = {
            "email_from": "mailer-daemon@example.com",
            "to": "bounce@example.com",
            "in_reply_to": "",
            "references": "",
            "body": "",
        }
        res = self.env["mail.thread"]._message_parse_extract_bounce(
            email_message, message_dict
        )
        self.assertEqual(res["bounced_partner"], partner)
        self.assertEqual(res["bounced_email"], "foo@bar.com")


@tagged("post_install", "-at_install")
class TestDuplicateMailLock(TransactionCase):
    def test_advisory_lock_uses_64bit_hash(self):
        """The inbound-mail dedup advisory lock must use the 64-bit
        ``hashtextextended`` (vs 32-bit ``hashtext``) so a hash collision does
        not treat two distinct Message-Ids as duplicates and drop the second
        inbound mail. This pins that the function exists and returns a bool.
        """
        self.env.cr.execute(
            "SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 0))",
            ["<some-message-id@example.com>"],
        )
        self.assertIsInstance(self.env.cr.fetchone()[0], bool)


@tagged("post_install", "-at_install")
class TestRecordByMessageUnknownModel(MailCommon):
    def test_helpers_skip_uninstalled_model(self):
        """A ``mail.message`` pointing at a model whose addon was uninstalled
        (rows are not cascade-cleaned) must not KeyError the store/notification
        render: the record-resolution helpers skip unknown models.
        """
        message = self.env["res.partner"].create({"name": "Host"}).message_post(
            body="orphan", message_type="comment", subtype_xmlid="mail.mt_note"
        )
        # ORM create refuses an unknown model (``_get_reply_to`` resolves it),
        # so simulate the leftover row of an uninstalled addon directly in SQL.
        self.env.cr.execute(
            "UPDATE mail_message SET model=%s, res_id=%s WHERE id=%s",
            ["x.gone.model", 1, message.id],
        )
        # Clean single-id recordset so prefetch does not pull sibling messages.
        orphan = self.env["mail.message"].browse(message.id)
        orphan.invalidate_recordset(["model", "res_id"])
        self.assertEqual(orphan.model, "x.gone.model")
        # Neither helper may raise; both simply skip the orphan message.
        self.assertEqual(orphan._records_by_model_name(), {})
        self.assertEqual(orphan._record_by_message(), {})


@tagged("post_install", "-at_install")
class TestScheduleMisPair(MailCommon):
    def test_every_schedule_notifies_its_own_message(self):
        """Each ``mail.message.schedule`` must trigger a notification for its own
        message. Two failure modes are pinned together:

        * two schedules sharing one ``mail_message_id`` (the old positional
          ``zip`` over the m2o-deduplicated ``mapped('mail_message_id.res_id')``
          dropped the tail schedule, then unlinked it unsent);
        * a group spanning several distinct messages (a naive
          ``schedules.mail_message_id.res_id`` scalar read raises
          ``Expected singleton``).
        """
        record = self.env["res.partner"].create({"name": "Sched"})
        message_a = record.message_post(
            body="a", message_type="comment", subtype_xmlid="mail.mt_note"
        )
        message_b = record.message_post(
            body="b", message_type="comment", subtype_xmlid="mail.mt_note"
        )
        now = fields.Datetime.now()
        schedules = self.env["mail.message.schedule"].create(
            [
                {"mail_message_id": message_a.id, "scheduled_datetime": now},
                {"mail_message_id": message_a.id, "scheduled_datetime": now},
                {"mail_message_id": message_b.id, "scheduled_datetime": now},
            ]
        )

        calls = []

        def _fake_notify(self, notif_message, **kwargs):
            calls.append(notif_message.id)

        # Patch on the record's registry class: the model's MRO resolves
        # ``_notify_thread`` to module overrides (e.g. sms) ahead of the base
        # mixin, so patching ``MailThread`` itself would not intercept the call.
        with patch.object(type(record), "_notify_thread", _fake_notify):
            schedules._send_notifications()

        self.assertEqual(
            sorted(calls), sorted([message_a.id, message_a.id, message_b.id])
        )
        self.assertFalse(schedules.exists())


@tagged("post_install", "-at_install")
class TestProcessEmailQueueExplicitIds(MailCommon):
    def test_explicit_ids_honored_beyond_search_cap(self):
        """An explicit ``email_ids`` request must send those mails even when
        more than ``batch_size * 10`` outgoing mails exist: the query is now
        narrowed to the ids instead of searching all outgoing mail (capped)
        and intersecting afterwards.
        """
        self.env["ir.config_parameter"].sudo().set_param(
            "mail.mail.queue.batch.size", "1"
        )  # cap becomes 1 * 10 = 10
        mails = self.env["mail.mail"].create(
            [{"state": "outgoing", "subject": f"m{i}"} for i in range(12)]
        )
        target = mails[0]  # lowest id -> sorts last under id desc -> beyond cap

        captured = []

        def _fake_send(self, *args, **kwargs):
            captured.extend(self.ids)

        with patch.object(type(self.env["mail.mail"]), "send", _fake_send):
            self.env["mail.mail"].process_email_queue(email_ids=target.ids)

        self.assertIn(target.id, captured)


@tagged("post_install", "-at_install")
class TestNotificationGC(MailCommon):
    def test_gc_collects_email_only_notifications(self):
        """Email-only notifications (``res_partner_id`` NULL) must be garbage
        collected. The old ``res_partner_id.partner_share = False`` clause
        required a partner, so those rows grew unbounded forever.
        """
        record = self.env["res.partner"].create({"name": "GC"})
        message = record.message_post(
            body="x", message_type="comment", subtype_xmlid="mail.mt_note"
        )
        notif = self.env["mail.notification"].create(
            {
                "mail_message_id": message.id,
                "res_partner_id": False,
                "mail_email_address": "ext@example.com",
                "notification_type": "email",
                "notification_status": "sent",
                "is_read": True,
            }
        )
        # Backdate past the GC horizon (write without is_read keeps read_date).
        notif.write({"read_date": fields.Datetime.now() - relativedelta(days=400)})

        self.env["mail.notification"]._gc_notifications(max_age_days=180)
        self.assertFalse(notif.exists())


@tagged("post_install", "-at_install")
class TestSubChannelMultiUserMention(MailCommon):
    def test_mention_partner_backed_by_two_users(self):
        """Auto-inviting a mentioned partner to a sub-channel must not crash
        when the partner backs several users: reading the notification-settings
        scalar off the multi-user recordset raised ``Expected singleton``.
        """
        partner = self.env["res.partner"].create({"name": "Dual"})
        self.env["res.users"].create(
            {"login": "dual_u1", "name": "Dual 1", "partner_id": partner.id}
        )
        self.env["res.users"].create(
            {"login": "dual_u2", "name": "Dual 2", "partner_id": partner.id}
        )
        self.assertEqual(len(partner.user_ids), 2)

        parent = self.env["discuss.channel"].create(
            {"name": "Parent", "channel_type": "channel"}
        )
        sub = self.env["discuss.channel"].create(
            {
                "name": "Sub",
                "channel_type": "channel",
                "parent_channel_id": parent.id,
            }
        )
        # Must not raise a singleton ValueError.
        sub.message_post(
            body="ping",
            partner_ids=partner.ids,
            message_type="comment",
            subtype_xmlid="mail.mt_comment",
        )
        self.assertIn(partner, sub.channel_partner_ids)
