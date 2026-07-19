"""Regression tests for the sixth mail hardening audit.

Each test pins a specific, empirically-confirmed finding so a future refactor
cannot silently reintroduce it. Backend-only for fast, deterministic runs.
Coverage: mail.message write ACL (notified-recipient tampering), mail.notification
forgery, the mail.mail SMTP-outage batch state guard, the mail.template
unsafe-expression scan scope, the mail.link.preview create race, the
notification-status store build under lost record access, and the
message_attachment_count onchange (NewId) computation.
"""

from unittest.mock import patch

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests.common import tagged
from odoo.tools import mute_logger

from odoo.addons.base.models.ir_mail_server import MailDeliveryException
from odoo.addons.mail.tests.common import MailCommon


@tagged("post_install", "-at_install", "mail_hardening_v6")
class TestMessageNotifiedWriteACL(MailCommon):
    """A message recipient (in partner_ids / with a mail.notification row) may
    READ the message but must NOT be able to WRITE it. Otherwise any notified
    user could rewrite the body/subject of a message they did not author, on a
    document they cannot even access.
    """

    def _documentless_message(self, author):
        # model=False removes any document-access confound: write can only be
        # granted by authorship or the (removed) notified shortcut.
        return (
            self.env["mail.message"]
            .sudo()
            .create(
                {
                    "body": "<p>ORIGINAL</p>",
                    "model": False,
                    "res_id": False,
                    "message_type": "comment",
                    "subtype_id": self.env.ref("mail.mt_comment").id,
                    "author_id": author.partner_id.id,
                    "partner_ids": [Command.set([self.user_employee.partner_id.id])],
                }
            )
        )

    def test_notified_recipient_cannot_write_message(self):
        message = self._documentless_message(self.user_admin)
        # the employee is a recipient -> may read
        message.with_user(self.user_employee).check_access("read")
        # ... but must not be able to alter it
        with self.assertRaises(AccessError):
            message.with_user(self.user_employee).check_access("write")
        with self.assertRaises(AccessError):
            message.with_user(self.user_employee).write({"body": "<p>FORGED</p>"})
        self.assertIn("ORIGINAL", message.sudo().body)

    def test_author_can_still_write_own_message(self):
        message = self._documentless_message(self.user_employee)
        message.with_user(self.user_employee).write({"body": "<p>edited</p>"})
        self.assertIn("edited", message.sudo().body)


@tagged("post_install", "-at_install", "mail_hardening_v6")
class TestNotificationForgery(MailCommon):
    """mail.notification.create must require WRITE access on the message (author
    or document write), not merely read: a notification grants its recipient
    visibility of / effective access to the message, so an unrestricted create
    let any user forge inbox items for arbitrary partners and self-grant access.
    """

    def test_forge_notification_for_arbitrary_partner_blocked(self):
        # documentless message authored by admin: the employee is neither the
        # author nor has any document write access to fall back on.
        message = (
            self.env["mail.message"]
            .sudo()
            .create(
                {
                    "body": "<p>note</p>",
                    "model": False,
                    "res_id": False,
                    "message_type": "comment",
                    "subtype_id": self.env.ref("mail.mt_note").id,
                    "author_id": self.partner_admin.id,
                }
            )
        )
        with self.assertRaises(AccessError):
            self.env["mail.notification"].with_user(self.user_employee).create(
                {
                    "mail_message_id": message.id,
                    "res_partner_id": self.user_admin.partner_id.id,
                    "notification_type": "inbox",
                }
            )

    def test_notify_pipeline_still_creates_notifications(self):
        """The legitimate (sudo) notify pipeline is unaffected."""
        partner = self.env["res.partner"].create({"name": "Recipient"})
        record = self.env["res.partner"].create({"name": "Doc"})
        record.message_subscribe(partner_ids=[partner.id])
        message = record.message_post(
            body="hi",
            partner_ids=[partner.id],
            message_type="comment",
            subtype_xmlid="mail.mt_comment",
        )
        self.assertTrue(
            self.env["mail.notification"].search_count(
                [("mail_message_id", "=", message.id)]
            ),
            "notify pipeline must still create notification rows",
        )


@tagged("post_install", "-at_install", "mail_hardening_v6")
class TestMailSmtpBatchStateGuard(MailCommon):
    """An SMTP connection failure must only flip mails that were actually
    'outgoing' to 'exception'; already-'sent' mails in the same recordset must
    be left untouched (else action_retry re-delivers them, duplicating email).
    """

    @mute_logger("odoo.addons.mail.models.mail_mail")
    def test_connect_failure_does_not_flip_sent_mail(self):
        sent = self.env["mail.mail"].create(
            {"body_html": "<p>a</p>", "state": "sent", "email_to": "a@test.lan"}
        )
        outgoing = self.env["mail.mail"].create(
            {"body_html": "<p>b</p>", "state": "outgoing", "email_to": "b@test.lan"}
        )
        batch = sent + outgoing

        def _boom(*args, **kwargs):
            raise MailDeliveryException("Unable to connect to SMTP Server")

        # the outgoing-server connection helper is `_connect__`
        with patch.object(
            type(self.env["ir.mail_server"]), "_connect__", side_effect=_boom
        ):
            batch.send(raise_exception=False)

        self.assertEqual(sent.state, "sent", "a delivered mail must not be reopened")
        self.assertEqual(
            outgoing.state, "exception", "the pending mail is marked as failed"
        )


@tagged("post_install", "-at_install", "mail_hardening_v6")
class TestTemplateUnsafeExpressionScope(MailCommon):
    """The dynamic-template editor gate (_has_unsafe_expression) must scan only
    the fields that are actually rendered. A non-rendered field (name,
    description) merely containing '{{ ... }}' text must not count as unsafe
    (and thus not require the editor group). Tested at the method level so the
    assertion is independent of the surrounding ACL/group plumbing.
    """

    def setUp(self):
        super().setUp()
        self.model_id = self.env.ref("base.model_res_partner").id

    def _make_template(self, **vals):
        # created as the (system) test admin -> the editor gate is bypassed, so
        # the row exists and we can probe _has_unsafe_expression() directly.
        return self.env["mail.template"].create(
            {
                "name": vals.get("name", "static"),
                "model_id": self.model_id,
                "subject": vals.get("subject", "static"),
                "body_html": vals.get("body_html", "<p>static</p>"),
            }
        )

    def test_dynamic_non_rendered_field_is_not_unsafe(self):
        # {{ non-whitelisted }} in the never-rendered `name` must NOT be flagged
        tmpl = self._make_template(name="Hi {{ object.email }}")
        self.assertFalse(
            tmpl._has_unsafe_expression(),
            "a dynamic expression in a non-rendered field must not be unsafe",
        )

    def test_dynamic_rendered_field_is_unsafe(self):
        # {{ non-whitelisted }} in a rendered field (subject) is still unsafe
        tmpl = self._make_template(subject="Hi {{ object.email }}")
        self.assertTrue(
            tmpl._has_unsafe_expression(),
            "a non-whitelisted expression in a rendered field must be unsafe",
        )

    def test_whitelisted_expression_is_safe(self):
        # a whitelisted expression in a rendered field is fine
        tmpl = self._make_template(subject="Hi {{ object.name }}")
        self.assertFalse(tmpl._has_unsafe_expression())


@tagged("post_install", "-at_install", "mail_hardening_v6")
class TestLinkPreviewRaceSafe(MailCommon):
    """Concurrent creation of a preview for the same brand-new source_url races
    the unique index; the IntegrityError must be absorbed (savepoint + re-search)
    instead of surfacing a 500.
    """

    @mute_logger("odoo.sql_db")
    def test_create_same_source_url_twice_does_not_crash(self):
        # The unique index on source_url naturally reproduces the race: a row
        # already exists, and the helper must absorb the IntegrityError from the
        # duplicate insert and resolve to the existing row instead of 500-ing.
        Preview = self.env["mail.link.preview"]
        url = "https://example.test/racy-article"
        existing = Preview.create({"source_url": url})

        result = Preview._create_from_values_race_safe([{"source_url": url}])

        self.assertEqual(
            result, existing, "must resolve to the row created by the racer"
        )
        self.assertEqual(
            Preview.search_count([("source_url", "=", url)]),
            1,
            "no duplicate preview row",
        )


@tagged("post_install", "-at_install", "mail_hardening_v6")
class TestNotificationStatusStoreLostAccess(MailCommon):
    """Building the notification-status store runs in the AUTHOR's env to render
    a delivery-failure notice. If the author lost access to the record since
    sending, reading the thread display_name unsudoed would raise AccessError
    *after* SMTP send, flipping a delivered mail to exception -> duplicate send.
    The display_name read must be sudo'd.
    """

    def test_store_build_does_not_raise_for_lost_access_author(self):
        from odoo.addons.mail.tools.discuss import Store

        author = self.user_employee
        # a private group channel the author is not a member of -> cannot read
        channel = self.env["discuss.channel"].create(
            {"name": "priv", "channel_type": "group"}
        )
        message = (
            self.env["mail.message"]
            .sudo()
            .create(
                {
                    "body": "<p>x</p>",
                    "model": "discuss.channel",
                    "res_id": channel.id,
                    "message_type": "comment",
                    "author_id": author.partner_id.id,
                }
            )
        )
        with self.assertRaises(AccessError):
            channel.with_user(author).check_access("read")
        store = Store()
        # must not raise
        message.with_user(author)._message_notifications_to_store(store)
        store.get_result()


@tagged("post_install", "-at_install", "mail_hardening_v6")
class TestMessageAttachmentCountOnchange(MailCommon):
    """message_attachment_count must key on _origin.id so it does not drop to 0
    for NewId records during an onchange.
    """

    def test_count_survives_new_id_record(self):
        partner = self.env["res.partner"].create({"name": "WithAttachment"})
        self.env["ir.attachment"].create(
            {
                "name": "a.txt",
                "res_model": "res.partner",
                "res_id": partner.id,
                "raw": b"hello",
            }
        )
        partner.invalidate_recordset(["message_attachment_count"])
        self.assertEqual(partner.message_attachment_count, 1)
        # simulate an onchange: a NewId record carrying the persisted origin
        new_record = partner.new(origin=partner)
        self.assertEqual(
            new_record.message_attachment_count,
            1,
            "count must resolve via _origin.id for NewId records",
        )


@tagged("post_install", "-at_install", "mail_hardening_v6")
class TestAliasNonAsciiSanitization(MailCommon):
    """A non-Latin alias name must be dropped (yielding a rejected/empty alias),
    not '?'-replaced into a garbage-but-'valid' dot-atom like '???'.
    """

    def test_non_latin_alias_is_rejected(self):
        Alias = self.env["mail.alias"]
        self.assertFalse(
            Alias._sanitize_alias_name("Привет"),
            "a purely non-Latin name must not sanitize to a '?'-filled alias",
        )
        self.assertEqual(Alias._sanitize_alias_name("abc Привет"), "abc-")
        # regular ASCII names are unaffected
        self.assertEqual(Alias._sanitize_alias_name("Hello World"), "hello-world")


@tagged("post_install", "-at_install", "mail_hardening_v6")
class TestChannelAvatarCacheKey(MailCommon):
    """avatar_cache_key is stored: populated, stable across reads, and recomputed
    only when its roots change (so serialization no longer re-hashes per read).
    """

    def test_cache_key_is_stored_and_stable(self):
        channel = self.env["discuss.channel"]._create_channel(
            name="Avatar", group_id=None
        )
        self.assertTrue(self.env["discuss.channel"]._fields["avatar_cache_key"].store)
        key = channel.avatar_cache_key
        self.assertTrue(key)
        channel.invalidate_recordset(["avatar_cache_key"])
        self.assertEqual(key, channel.avatar_cache_key, "must be stable across reads")

    def test_cache_key_recomputes_on_root_change(self):
        channel = self.env["discuss.channel"]._create_channel(
            name="Avatar2", group_id=None
        )
        before = channel.avatar_cache_key
        channel.uuid = "regression-v6-uuid-0001"
        self.assertNotEqual(before, channel.avatar_cache_key)


@tagged("post_install", "-at_install", "mail_hardening_v6")
class TestLinkPreviewNotifyMultiMessage(MailCommon):
    """_unlink_and_notify / _hide_and_notify must compute the bus channel
    per-record: self._bus_channel() ensure_one()s, so a recordset spanning two
    messages used to crash.
    """

    def _message_link_preview(self, channel, url):
        message = channel.message_post(body="hi")
        preview = self.env["mail.link.preview"].create({"source_url": url})
        return self.env["mail.message.link.preview"].create(
            {"message_id": message.id, "link_preview_id": preview.id}
        )

    def test_unlink_and_notify_across_two_messages(self):
        ch1 = self.env["discuss.channel"]._create_channel(name="LP1", group_id=None)
        ch2 = self.env["discuss.channel"]._create_channel(name="LP2", group_id=None)
        mlp = self._message_link_preview(
            ch1, "https://example.test/lp-a"
        ) + self._message_link_preview(ch2, "https://example.test/lp-b")
        self.assertEqual(len(mlp.message_id), 2)
        # would raise "Expected singleton" before the per-record fix
        mlp._unlink_and_notify()
        self.assertFalse(mlp.exists())


@tagged("post_install", "-at_install", "mail_hardening_v6")
class TestMessageCreateUidSearchSymmetry(MailCommon):
    """_check_access("read") allows create_uid == uid; _search must match, else a
    message a user created on behalf of another author is readable by id yet
    never returned by search (asymmetry).
    """

    def test_creator_can_search_own_created_message(self):
        creator = self.user_employee
        other_author = self.env["res.partner"].create({"name": "OtherAuthor"})
        doc = self.env["res.partner"].create({"name": "Doc"})
        message = (
            self.env["mail.message"]
            .sudo()
            .create(
                {
                    "body": "<p>x</p>",
                    "model": "res.partner",
                    "res_id": doc.id,
                    "message_type": "comment",
                    "subtype_id": self.env.ref("mail.mt_note").id,
                    "author_id": other_author.id,
                    "create_uid": creator.id,
                }
            )
        )
        message.with_user(creator).check_access("read")  # readable
        found = (
            self.env["mail.message"].with_user(creator).search([("id", "=", message.id)])
        )
        self.assertEqual(found, message, "a created message must be searchable too")

    def test_unrelated_message_stays_unsearchable(self):
        # control: a documentless message the employee neither created, authored,
        # nor is notified on must NOT become searchable (the create_uid allow
        # must match only the *caller's* own create_uid). model=False removes any
        # document-access confound.
        message = (
            self.env["mail.message"]
            .sudo()
            .create(
                {
                    "body": "<p>secret</p>",
                    "model": False,
                    "res_id": False,
                    "message_type": "comment",
                    "subtype_id": self.env.ref("mail.mt_note").id,
                    "author_id": self.partner_admin.id,
                    "create_uid": self.user_admin.id,
                }
            )
        )
        found = (
            self.env["mail.message"]
            .with_user(self.user_employee)
            .search([("id", "=", message.id)])
        )
        self.assertFalse(found)


@tagged("post_install", "-at_install", "mail_hardening_v6")
class TestPushDeviceEndpointRotation(MailCommon):
    """register_devices' rotation path must not violate _endpoint_unique when the
    new endpoint already exists on another (superseded) row.
    """

    def test_rotation_into_conflicting_endpoint(self):
        Device = self.env["mail.push.device"]
        vapid = Device.get_web_push_vapid_public_key()  # establish key first
        other = self.env["res.partner"].create({"name": "OtherDeviceOwner"})
        dev_other = Device.sudo().create(
            {"endpoint": "https://p/rot-1", "keys": "{}", "partner_id": other.id}
        )
        dev_self = Device.sudo().create(
            {
                "endpoint": "https://p/rot-2",
                "keys": "{}",
                "partner_id": self.env.user.partner_id.id,
            }
        )
        # rotate self's endpoint onto the endpoint currently held by `other`
        Device.register_devices(
            vapid_public_key=vapid,
            endpoint="https://p/rot-1",
            previous_endpoint="https://p/rot-2",
            keys={"p256dh": "x", "auth": "y"},
        )
        dev_self.invalidate_recordset(["endpoint"])
        self.assertTrue(dev_self.exists())
        self.assertEqual(dev_self.endpoint, "https://p/rot-1")
        self.assertFalse(dev_other.exists(), "superseded row must be dropped")
        self.assertEqual(
            Device.sudo().search_count([("endpoint", "=", "https://p/rot-1")]), 1
        )


@tagged("post_install", "-at_install", "mail_hardening_v6")
class TestScheduledMessagePagination(MailCommon):
    """mail.scheduled.message._search must apply the caller's LIMIT/OFFSET to the
    ACCESSIBLE rows, not the raw SQL window — otherwise inaccessible rows filling
    the window shrink/empty the page.
    """

    def test_page_fills_past_inaccessible_rows(self):
        from unittest.mock import patch

        employee = self.user_employee
        env = self.env(user=employee)
        docs = self.env["res.partner"].create([{"name": f"D{i}"} for i in range(5)])
        scheduled = env["mail.scheduled.message"]
        for doc in docs:
            scheduled |= env["mail.scheduled.message"].create(
                {
                    "model": "res.partner",
                    "res_id": doc.id,
                    "body": "<p>later</p>",
                    "author_id": employee.partner_id.id,
                    "scheduled_date": "2999-01-01 00:00:00",
                }
            )
        # simulate the first 3 documents (in id order) being inaccessible
        inaccessible = docs[:3]
        real_filtered = type(self.env["res.partner"])._filtered_access

        def fake_filtered(records, operation):
            return real_filtered(records - inaccessible, operation)

        with patch.object(
            type(self.env["res.partner"]), "_filtered_access", fake_filtered
        ):
            # a limit-2 search must still return 2 ACCESSIBLE scheduled messages
            page = env["mail.scheduled.message"].search([], limit=2, order="res_id")
        self.assertEqual(len(page), 2, "page must fill past inaccessible rows")
        self.assertTrue(
            all(m.res_id in docs[3:].ids for m in page),
            "only accessible scheduled messages must be returned",
        )


@tagged("post_install", "-at_install", "mail_hardening_v6")
class TestMailSendErrorClassification(MailCommon):
    """_classify_send_error centralizes _send's delivery-failure taxonomy; pin
    its mapping so a refactor cannot silently change failure_type/reason.
    """

    def setUp(self):
        super().setUp()
        self.Mail = self.env["mail.mail"]
        self.IrMailServer = self.env["ir.mail_server"]

    def test_outgoing_email_error_from_codes(self):
        from odoo.addons.base.models.ir_mail_server import OutgoingEmailError

        ftype, reason = self.Mail._classify_send_error(
            OutgoingEmailError("bad from", code=self.IrMailServer.NO_VALID_FROM)
        )
        self.assertEqual(ftype, "mail_from_invalid")
        self.assertEqual(reason, "bad from")

        ftype, __ = self.Mail._classify_send_error(
            OutgoingEmailError("missing", code=self.IrMailServer.NO_FOUND_FROM)
        )
        self.assertEqual(ftype, "mail_from_missing")

    def test_outbound_spam_is_mail_spam(self):
        ftype, __ = self.Mail._classify_send_error(
            MailDeliveryException("OutboundSpamException: rejected")
        )
        self.assertEqual(ftype, "mail_spam")

    def test_generic_falls_back_to_unknown(self):
        ftype, reason = self.Mail._classify_send_error(ValueError("boom"))
        self.assertEqual(ftype, "unknown")
        self.assertEqual(reason, "boom")

    def test_preserves_prior_classification(self):
        # an unrelated exception must not clobber a failure_type already inferred
        ftype, reason = self.Mail._classify_send_error(
            ValueError("boom"),
            failure_type="mail_email_invalid",
            failure_reason="earlier",
        )
        self.assertEqual(ftype, "mail_email_invalid")
        self.assertEqual(reason, "earlier")
