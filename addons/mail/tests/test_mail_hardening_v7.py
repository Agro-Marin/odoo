"""Regression tests for the seventh mail hardening audit.

Each test pins a specific, empirically-confirmed finding so a future refactor
cannot silently reintroduce it. Coverage:

 - public / none-auth discuss + mail routes must coerce client-supplied record
   ids: a non-numeric id used to reach an integer-typed domain (or a bare
   ``int()``) and surface a psycopg ``InvalidTextRepresentation`` -- an
   anonymous unhandled-exception / HTTP-500 primitive -- instead of a clean
   ``NotFound``;
 - routes taking a client-supplied model name must validate it (an unknown
   model name used to ``KeyError`` -> 500);
 - ``mail.notification._gc_notifications`` must collect read, aged, terminal
   notifications for *share* (portal / customer) partners, not only internal
   users and email-only rows -- otherwise ``mail_notification`` (one of the
   largest tables on portal databases) grew without bound.
"""

import json
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests import HttpCase, tagged
from odoo.tools import mute_logger

from odoo.addons.mail.tests.common import MailCommon, mail_new_test_user


@tagged("-at_install", "post_install", "mail_hardening_v7")
class TestControllerInputCoercion(HttpCase, MailCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.public_channel = cls.env["discuss.channel"].create(
            {"group_public_id": None, "name": "Hardening v7 channel"}
        )

    def _post(self, url, params):
        return self.url_open(
            url,
            data=json.dumps({"params": params}),
            headers={"Content-Type": "application/json"},
        )

    @staticmethod
    def _error_name(res):
        try:
            return res.json().get("error", {}).get("data", {}).get("name") or ""
        except ValueError:
            return ""

    @mute_logger("odoo.http")
    def test_public_route_non_numeric_channel_id_is_notfound_not_server_error(self):
        """A non-numeric channel_id on a public jsonrpc route must resolve to a
        clean NotFound, never a psycopg InvalidTextRepresentation server error."""
        self.authenticate(None, None)
        cases = [
            ("/discuss/channel/pinned_messages", {"channel_id": "not-an-int"}),
            (
                "/discuss/channel/mark_as_read",
                {"channel_id": "not-an-int", "last_message_id": 1},
            ),
            (
                "/discuss/channel/notify_typing",
                {"channel_id": "not-an-int", "is_typing": True},
            ),
            ("/discuss/channel/join", {"channel_id": "not-an-int"}),
        ]
        for url, params in cases:
            with self.subTest(url=url):
                name = self._error_name(self._post(url, params))
                self.assertNotIn(
                    "InvalidTextRepresentation",
                    name,
                    "anonymous caller reached a raw integer domain -> 500",
                )
                self.assertEqual(name, "werkzeug.exceptions.NotFound")

    def test_valid_channel_id_still_resolves(self):
        """The coercion must not break the happy path."""
        self.authenticate(None, None)
        res = self._post(
            "/discuss/channel/pinned_messages",
            {"channel_id": self.public_channel.id},
        )
        self.assertEqual(res.status_code, 200)
        self.assertFalse(self._error_name(res), "valid id should not error")

    @mute_logger("odoo.http")
    def test_unfollow_non_numeric_ids_is_404_not_500(self):
        """/mail/unfollow is type=http: a non-numeric res_id/pid used to raise a
        bare ValueError -> HTTP 500. It must now be a clean 404."""
        self.authenticate(None, None)
        for query in (
            "model=res.partner&res_id=abc&pid=1&token=x",
            "model=res.partner&res_id=1&pid=abc&token=x",
        ):
            with self.subTest(query=query):
                res = self.url_open(f"/mail/unfollow?{query}")
                self.assertEqual(res.status_code, 404)

    @mute_logger("odoo.http")
    def test_post_unknown_model_is_notfound_not_keyerror(self):
        """/mail/message/post resolves the thread through a client-supplied
        model name; an unknown model must be NotFound, not a KeyError 500."""
        self.authenticate(None, None)
        name = self._error_name(
            self._post(
                "/mail/message/post",
                {
                    "thread_model": "not.a.model",
                    "thread_id": 1,
                    "post_data": {"body": "x"},
                },
            )
        )
        self.assertNotIn("KeyError", name)
        self.assertEqual(name, "werkzeug.exceptions.NotFound")


@tagged("-at_install", "post_install", "mail_hardening_v7")
class TestNotificationGcSharePartner(MailCommon):
    """``_gc_notifications`` must not permanently spare share partners."""

    def _aged_read_notification(self, partner, message):
        notif = self.env["mail.notification"].create(
            {
                "mail_message_id": message.id,
                "res_partner_id": partner.id,
                "notification_type": "email",
                "notification_status": "sent",
                "is_read": True,
            }
        )
        # read_date is stamped to now() at create; force it past the GC horizon.
        old = fields.Datetime.now() - timedelta(days=200)
        self.env.cr.execute(
            "UPDATE mail_notification SET read_date = %s WHERE id = %s",
            (old, notif.id),
        )
        notif.invalidate_recordset(["read_date"])
        return notif

    def test_gc_collects_share_partner_notification(self):
        portal_user = mail_new_test_user(
            self.env,
            login="hv7_portal",
            groups="base.group_portal",
            name="Portal Customer",
        )
        share_partner = portal_user.partner_id
        internal_partner = self.env.ref("base.user_admin").partner_id
        self.assertTrue(share_partner.partner_share, "portal partner must be share")
        self.assertFalse(internal_partner.partner_share)

        message = self.env["mail.message"].create(
            {"subject": "gc v7", "message_type": "email"}
        )
        share_notif = self._aged_read_notification(share_partner, message)
        internal_notif = self._aged_read_notification(internal_partner, message)

        self.env["mail.notification"]._gc_notifications()

        self.assertFalse(
            share_notif.exists(),
            "read, 200-day-old notification for a SHARE partner must be GC'd",
        )
        self.assertFalse(
            internal_notif.exists(),
            "internal-user notification must still be GC'd (control)",
        )


@tagged("-at_install", "post_install", "mail_hardening_v7")
class TestMessageSearchCountCap(MailCommon):
    """``_message_fetch`` must cap the in-thread search count instead of running
    an unbounded, access-filtered scan of the whole thread on every keystroke."""

    def test_search_count_is_capped(self):
        channel = self.env["discuss.channel"].create(
            {"name": "cap", "group_public_id": False}
        )
        Message = self.env["mail.message"]
        subtype = self.env.ref("mail.mt_comment").id
        for i in range(8):
            Message.create(
                {
                    "model": "discuss.channel",
                    "res_id": channel.id,
                    "body": f"<p>zzcap {i}</p>",
                    "message_type": "comment",
                    "subtype_id": subtype,
                }
            )

        # fewer matches than the cap -> exact count
        exact = Message._message_fetch(
            domain=None, thread=channel, search_term="zzcap"
        )
        self.assertEqual(exact["count"], 8)

        # more matches than the cap -> count is bounded, page fetch unaffected
        with patch.object(type(Message), "_SEARCH_COUNT_CAP", 5):
            capped = Message._message_fetch(
                domain=None, thread=channel, search_term="zzcap"
            )
        self.assertEqual(capped["count"], 5, "count must be capped, not exhaustive")
        self.assertTrue(capped["messages"], "capping the count must not empty the page")


@tagged("-at_install", "post_install", "mail_hardening_v7")
class TestGatewayReplyCorrelationSudo(MailCommon):
    """Threading an inbound reply/bounce to its referenced message is a header
    match that must not depend on the gateway user's ACL."""

    def test_parent_correlation_ignores_caller_acl(self):
        parent = self.env["mail.message"].create(
            {
                "model": False,  # pure log: not readable via search by a bystander
                "message_type": "email",
                "message_id": "<hv7-parent@test>",
                "subject": "parent",
                "body": "<p>parent</p>",
            }
        )
        # Confirm the premise: the employee genuinely cannot read it by search,
        # so a non-sudo correlation would return empty.
        self.assertFalse(
            self.env["mail.message"]
            .with_user(self.user_employee)
            .search([("message_id", "=", "<hv7-parent@test>")]),
            "test premise: message must be unreadable by the bystander",
        )

        found = (
            self.env["mail.thread"]
            .with_user(self.user_employee)
            ._get_parent_message(
                {"in_reply_to": "<hv7-parent@test>", "references": ""}
            )
        )
        self.assertEqual(
            found,
            parent,
            "reply correlation must find the parent regardless of caller ACL",
        )
