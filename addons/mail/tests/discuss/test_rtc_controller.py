from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests import JsonRpcException, tagged

from odoo.addons.mail.tests.common import mail_new_test_user
from odoo.addons.mail.tests.common_controllers import MailControllerCommon


@tagged("-at_install", "post_install", "mail_controller")
class TestRtcController(MailControllerCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user_a = mail_new_test_user(
            cls.env, login="rtc_a", groups="base.group_user", name="Rtc A"
        )
        cls.user_b = mail_new_test_user(
            cls.env, login="rtc_b", groups="base.group_user", name="Rtc B"
        )
        cls.channel = (
            cls.env["discuss.channel"]
            .with_user(cls.user_a)
            ._create_group(
                partners_to=[cls.user_a.partner_id.id, cls.user_b.partner_id.id],
                name="Rtc Group",
            )
        )
        members = cls.channel.channel_member_ids
        cls.member_a = members.filtered(lambda m: m.partner_id == cls.user_a.partner_id)
        cls.member_b = members.filtered(lambda m: m.partner_id == cls.user_b.partner_id)
        cls.session_a, cls.session_b = (
            cls.env["discuss.channel.rtc.session"]
            .sudo()
            .create(
                [
                    {"channel_id": cls.channel.id, "channel_member_id": member.id}
                    for member in (cls.member_a, cls.member_b)
                ]
            )
        )
        cls.Session = type(cls.env["discuss.channel.rtc.session"])

    def assertRefused(self, route, params, msg):
        with self.assertRaises(JsonRpcException, msg=msg) as capture:
            self.call_jsonrpc(route, params)
        self.assertEqual(capture.exception.code, 404, msg)

    def test_notify_call_members_ignores_a_session_the_caller_does_not_own(self):
        self.authenticate("rtc_a", "rtc_a")
        notified = []
        notify_peers = self.Session._notify_peers

        def spy(session, notifications):
            notified.append(session.id)
            return notify_peers(session, notifications)

        with patch.object(self.Session, "_notify_peers", spy):
            self.call_jsonrpc(
                "/mail/rtc/session/notify_call_members",
                {
                    "peer_notifications": [
                        [self.session_b.id, [self.session_a.id], "stolen"]
                    ]
                },
            )
            self.assertEqual(notified, [], "another user's session sent a notification")
            self.call_jsonrpc(
                "/mail/rtc/session/notify_call_members",
                {
                    "peer_notifications": [
                        [self.session_a.id, [self.session_b.id], "mine"]
                    ]
                },
            )
        self.assertEqual(notified, [self.session_a.id])

    def test_update_and_broadcast_ignores_a_session_the_caller_does_not_own(self):
        self.authenticate("rtc_a", "rtc_a")
        self.call_jsonrpc(
            "/mail/rtc/session/update_and_broadcast",
            {"session_id": self.session_b.id, "values": {"is_camera_on": True}},
        )
        self.session_b.invalidate_recordset()
        self.assertFalse(
            self.session_b.is_camera_on, "another user's session was updated"
        )
        self.call_jsonrpc(
            "/mail/rtc/session/update_and_broadcast",
            {"session_id": self.session_a.id, "values": {"is_camera_on": True}},
        )
        self.session_a.invalidate_recordset()
        self.assertTrue(self.session_a.is_camera_on)

    def test_update_and_broadcast_rejects_values_that_are_not_a_mapping(self):
        self.authenticate("rtc_a", "rtc_a")
        for values in (["is_camera_on"], "is_camera_on", 1, None):
            with self.subTest(values=values):
                self.assertRefused(
                    "/mail/rtc/session/update_and_broadcast",
                    {"session_id": self.session_a.id, "values": values},
                    "values that are not a mapping must be refused, not crash",
                )

    def test_cancel_call_invitation_requires_membership(self):
        outsider = mail_new_test_user(
            self.env, login="rtc_out", groups="base.group_user", name="Rtc Out"
        )
        self.member_b.sudo().rtc_inviting_session_id = self.session_a
        self.authenticate("rtc_out", "rtc_out")
        self.assertRefused(
            "/mail/rtc/channel/cancel_call_invitation",
            {"channel_id": self.channel.id, "member_ids": [self.member_b.id]},
            "a non-member cancelled another channel's invitations",
        )
        self.member_b.invalidate_recordset()
        self.assertEqual(self.member_b.rtc_inviting_session_id, self.session_a)
        self.assertFalse(
            outsider.partner_id in self.channel.channel_member_ids.partner_id
        )
        self.authenticate("rtc_a", "rtc_a")
        self.call_jsonrpc(
            "/mail/rtc/channel/cancel_call_invitation",
            {"channel_id": self.channel.id, "member_ids": [self.member_b.id]},
        )
        self.member_b.invalidate_recordset()
        self.assertFalse(self.member_b.rtc_inviting_session_id)

    def test_channel_ping_refreshes_only_the_callers_session(self):
        self.authenticate("rtc_a", "rtc_a")
        stale = fields.Datetime.now() - timedelta(seconds=30)
        self.env.cr.execute(
            "UPDATE discuss_channel_rtc_session SET write_date = %s WHERE id = ANY(%s)",
            (stale, [self.session_a.id, self.session_b.id]),
        )
        (self.session_a | self.session_b).invalidate_recordset(["write_date"])
        result = self.call_jsonrpc(
            "/discuss/channel/ping",
            {"channel_id": self.channel.id, "rtc_session_id": self.session_b.id},
        )
        (self.session_a | self.session_b).invalidate_recordset(["write_date"])
        self.assertEqual(
            self.session_b.write_date, stale, "another user's session was refreshed"
        )
        self.assertIn(
            ["ADD", [self.session_a.id, self.session_b.id]],
            result["discuss.channel"][0]["rtc_session_ids"],
            "the ping is still answered with the channel's sessions",
        )
        self.call_jsonrpc(
            "/discuss/channel/ping",
            {"channel_id": self.channel.id, "rtc_session_id": self.session_a.id},
        )
        self.session_a.invalidate_recordset(["write_date"])
        self.assertGreater(self.session_a.write_date, stale)

    def test_rtc_routes_reject_unparseable_ids(self):
        self.authenticate("rtc_a", "rtc_a")
        cases = (
            (
                "/discuss/channel/ping",
                {"channel_id": self.channel.id, "check_rtc_session_ids": "junk"},
            ),
            (
                "/discuss/channel/ping",
                {"channel_id": self.channel.id, "rtc_session_id": "junk"},
            ),
            (
                "/mail/rtc/channel/join_call",
                {"channel_id": self.channel.id, "check_rtc_session_ids": "junk"},
            ),
            (
                "/mail/rtc/channel/join_call",
                {"channel_id": self.channel.id, "check_rtc_session_ids": [1, "x"]},
            ),
            (
                "/mail/rtc/channel/leave_call",
                {"channel_id": self.channel.id, "session_id": "junk"},
            ),
            (
                "/mail/rtc/channel/cancel_call_invitation",
                {"channel_id": self.channel.id, "member_ids": "junk"},
            ),
        )
        for route, params in cases:
            with self.subTest(route=route, params=params):
                self.assertRefused(route, params, "unparseable ids must be a 404")

    def test_channel_ping_still_reports_outdated_sessions(self):
        self.authenticate("rtc_a", "rtc_a")
        result = self.call_jsonrpc(
            "/discuss/channel/ping",
            {
                "channel_id": self.channel.id,
                "check_rtc_session_ids": [self.session_a.id, 0x7FFFFFF],
            },
        )
        self.assertIn(
            ["DELETE", [0x7FFFFFF]],
            result["discuss.channel"][0]["rtc_session_ids"],
        )
