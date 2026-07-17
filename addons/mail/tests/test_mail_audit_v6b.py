"""Regression tests (part b) for the sixth mail audit.

Pins the non-obvious performance / security / correctness fixes that lacked a
direct test: the O(N^2) inbox payload reduction (and the email-address leak it
closed), the channel-invite membership gate, and the web-push retry of a
transiently-unresolvable endpoint.
"""

import json
from unittest.mock import patch

from odoo.exceptions import AccessError
from odoo.tests.common import tagged

from odoo.addons.mail.tests.common import MailCommon
from odoo.addons.mail.tools.discuss import Store


@tagged("post_install", "-at_install")
class TestInboxNotificationPayload(MailCommon):
    def test_inbox_payload_excludes_notification_ids(self):
        """The inbox fan-out payload must NOT embed the message's
        notification_ids (that made it O(recipients^2) and leaked every other
        recipient's email address), while the chatter/_to_store path still
        includes them for the delivery-status UI."""
        user = self.user_employee
        user.notification_type = "inbox"
        record = self.env["res.partner"].create({"name": "InboxTarget"})
        record.message_subscribe(partner_ids=user.partner_id.ids)

        inbox_events = []
        Users = self.env.registry["res.users"]
        orig_bus_send = Users._bus_send

        def spy(self2, notification_type, message=None, **kw):
            if notification_type == "mail.message/inbox":
                inbox_events.append(message)
            return orig_bus_send(self2, notification_type, message, **kw)

        with patch.object(Users, "_bus_send", spy):
            message = record.message_post(
                body="hi",
                partner_ids=user.partner_id.ids,
                message_type="comment",
                subtype_xmlid="mail.mt_comment",
            )
        self.assertEqual(len(inbox_events), 1, "the follower should get one inbox event")
        self.assertNotIn(
            "notification_ids",
            json.dumps(inbox_events, default=str),
            "inbox payload must not carry the per-message notification list",
        )
        # chatter path (no mail_notify_inbox flag) still includes it
        store = Store()
        store.add(message)
        self.assertIn(
            "notification_ids",
            json.dumps(store.get_result(), default=str),
            "chatter serialization must still expose delivery status",
        )


@tagged("post_install", "-at_install")
class TestChannelInviteMembershipGate(MailCommon):
    def test_non_member_cannot_invite_by_email(self):
        """invite_by_email sends outbound mail through the company server, so it
        must require membership, not mere read access to a public channel."""
        channel = self.env["discuss.channel"]._create_channel(
            name="PubChan", group_id=None
        )
        self.assertTrue(channel._allow_invite_by_email())
        as_employee = channel.with_user(self.user_employee)  # not a member
        self.assertTrue(as_employee.name)  # can read the public channel
        with self.assertRaises(AccessError):
            as_employee.invite_by_email(["outsider@ext.example.com"])


@tagged("post_install", "-at_install")
class TestWebPushRetry(MailCommon):
    def test_unresolvable_endpoint_is_kept_for_retry(self):
        """A transient PushEndpointUnresolvableError must keep the queued
        mail.push row for the next cron run, not unlink it."""
        icp = self.env["ir.config_parameter"].sudo()
        icp.set_param("mail.web_push_vapid_private_key", "test-priv")
        icp.set_param("mail.web_push_vapid_public_key", "test-pub")
        device = self.env["mail.push.device"].create(
            {
                "partner_id": self.user_employee.partner_id.id,
                "endpoint": "https://push.example.com/ep",
                "keys": json.dumps({"p256dh": "k", "auth": "a"}),
            }
        )
        push = self.env["mail.push"].create(
            {"mail_push_device_id": device.id, "payload": "{}"}
        )
        from odoo.addons.mail.models import mail_push as mail_push_module
        from odoo.addons.mail.tools.web_push import PushEndpointUnresolvableError

        def raise_unresolvable(*args, **kwargs):
            raise PushEndpointUnresolvableError

        with patch.object(mail_push_module, "push_to_end_point", raise_unresolvable):
            self.env["mail.push"]._push_notification_to_endpoint()
        self.assertTrue(
            push.exists(),
            "an unresolvable push must be kept for retry, not deleted",
        )
        self.assertTrue(device.exists(), "the device must be kept too")
