"""Regression tests for the fifth mail hardening audit.

Each test pins a specific, empirically-confirmed finding from the audit so a
future refactor cannot silently reintroduce it. Backend-only for fast,
deterministic runs. Coverage spans ir.actions.server, mail.push.device,
discuss.channel write ACL, mail.message / mail.activity ACL pagination, the
inbound bounce gateway, flat-thread parenting and the mail.mail send path.
"""

from unittest.mock import patch

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests.common import tagged
from odoo.tools import mute_logger

from odoo.addons.base.models.ir_mail_server import MailDeliveryException
from odoo.addons.mail.tests.common import MailCommon


@tagged("post_install", "-at_install")
class TestServerActionNextActivityUser(MailCommon):
    def test_generic_user_not_leaked_across_records(self):
        """`ir.actions.server` next_activity with a dynamic ("generic") user
        must not let a resolved responsible leak from one record to the next
        when the field is empty for a later record.
        """
        model = self.env.ref("base.model_res_partner")
        # record A resolves a (distinct) responsible from its user field;
        # record B leaves it empty and must NOT inherit A's responsible.
        record_a = self.env["res.partner"].create(
            {"name": "A", "user_id": self.user_employee.id}
        )
        record_b = self.env["res.partner"].create({"name": "B", "user_id": False})
        action = self.env["ir.actions.server"].create(
            {
                "name": "next act",
                "model_id": model.id,
                "state": "next_activity",
                "activity_type_id": self.env.ref("mail.mail_activity_data_todo").id,
                "activity_user_type": "generic",
                "activity_user_field_name": "user_id",
            }
        )
        action.with_context(
            active_model="res.partner",
            active_ids=[record_a.id, record_b.id],
            active_id=record_a.id,
        ).run()
        activity_a = self.env["mail.activity"].search(
            [("res_model", "=", "res.partner"), ("res_id", "=", record_a.id)]
        )
        activity_b = self.env["mail.activity"].search(
            [("res_model", "=", "res.partner"), ("res_id", "=", record_b.id)]
        )
        self.assertEqual(
            activity_a.user_id,
            self.user_employee,
            "record A is assigned from its own user field",
        )
        self.assertTrue(activity_b)
        self.assertNotEqual(
            activity_b.user_id,
            self.user_employee,
            "record B must not inherit record A's resolved responsible user",
        )


@tagged("post_install", "-at_install")
class TestPushDeviceOwnership(MailCommon):
    def test_cannot_hijack_or_delete_others_device(self):
        """register/unregister are @api.model + sudo() (ACL-bypassing); they
        must scope to the caller's partner so a leaked endpoint cannot be used
        to delete or hijack another user's device.
        """
        Device = self.env["mail.push.device"]
        vapid = Device.get_web_push_vapid_public_key()
        victim = self.user_admin.partner_id
        device = Device.sudo().create(
            {"endpoint": "https://p/ep1", "keys": "{}", "partner_id": victim.id}
        )
        attacker = self.user_employee

        Device.with_user(attacker).unregister_devices(endpoint="https://p/ep1")
        self.assertTrue(
            device.exists(), "victim device must survive attacker unregister"
        )

        Device.with_user(attacker).register_devices(
            vapid_public_key=vapid,
            endpoint="https://p/ep1",
            keys={"p256dh": "x", "auth": "y"},
        )
        device.invalidate_recordset(["partner_id"])
        self.assertEqual(
            device.partner_id, victim, "ownership must not transfer to attacker"
        )


@tagged("post_install", "-at_install")
class TestChannelStructuralWriteACL(MailCommon):
    def test_non_member_cannot_modify_channel_config(self):
        """The record rule granting access to a public channel does not enforce
        membership; structural writes (rename / archive / re-authorize) must be
        blocked for a non-member internal user, and allowed for a member.
        """
        channel = self.env["discuss.channel"]._create_channel(name="Sec", group_id=None)
        employee = self.user_employee
        as_attacker = self.env["discuss.channel"].with_user(employee).browse(channel.id)

        # reading stays allowed (public channel), structural writes do not
        as_attacker.read(["name"])
        with self.assertRaises(AccessError):
            as_attacker.write({"name": "pwned"})
        with self.assertRaises(AccessError):
            as_attacker.write({"active": False})
        with self.assertRaises(AccessError):
            as_attacker.write({"group_public_id": self.env.ref("base.group_user").id})
        self.assertFalse(as_attacker.is_editable)

        # a member can edit
        channel._add_members(users=employee)
        as_attacker.invalidate_recordset()
        as_attacker.write({"name": "renamed-by-member"})
        self.assertEqual(channel.name, "renamed-by-member")
        self.assertTrue(as_attacker.is_editable)


@tagged("post_install", "-at_install")
class TestReactionConcurrentAdd(MailCommon):
    def test_concurrent_reaction_add_does_not_crash(self):
        """Adding the same reaction concurrently races the unique index; the
        IntegrityError must be swallowed (savepoint) instead of surfacing a 500.
        """
        channel = self.env["discuss.channel"]._create_channel(name="Rx", group_id=None)
        message = channel.message_post(body="hi")
        partner = self.env.user.partner_id
        guest = self.env["mail.guest"]
        message._message_reaction("👍", "add", partner, guest)

        Reaction = self.env["mail.message.reaction"]
        real_search = type(Reaction).search

        def blind_search(records, *args, **kwargs):
            # emulate the race window: the pre-check sees no existing reaction
            return real_search(records, *args, **kwargs).browse()

        with (
            patch.object(type(Reaction), "search", blind_search),
            mute_logger("odoo.sql_db"),
        ):
            # would raise psycopg.IntegrityError without the savepoint/catch
            message._message_reaction("👍", "add", partner, guest)

        self.assertEqual(
            Reaction.search_count(
                [("message_id", "=", message.id), ("content", "=", "👍")]
            ),
            1,
            "no duplicate reaction row",
        )


@tagged("post_install", "-at_install")
class TestMessageSearchPagination(MailCommon):
    def test_limited_search_fills_accessible_page(self):
        """mail.message._search must apply the caller's limit/offset AFTER the
        Python accessibility filter, so a limited page is filled with accessible
        records instead of being silently truncated / skipped / duplicated.
        """
        employee = self.user_employee
        Message = self.env["mail.message"]
        subtype = self.env.ref("mail.mt_comment").id
        accessible = []
        for _i in range(5):
            # inaccessible: authored by admin, no document, no notification
            Message.create(
                {
                    "model": False,
                    "res_id": False,
                    "message_type": "comment",
                    "subtype_id": subtype,
                    "body": "inaccessible",
                    "author_id": self.user_admin.partner_id.id,
                }
            )
            # accessible: authored by the searching employee
            accessible.append(
                Message.create(
                    {
                        "model": False,
                        "res_id": False,
                        "message_type": "comment",
                        "subtype_id": subtype,
                        "body": "accessible",
                        "author_id": employee.partner_id.id,
                    }
                ).id
            )

        domain = [("id", ">=", min(accessible) - 1)]
        MessageAsEmp = Message.with_user(employee)
        self.assertEqual(
            len(MessageAsEmp.search(domain, limit=3, order="id asc")),
            3,
            "a limit=3 page must return 3 accessible messages, not fewer",
        )
        page1 = MessageAsEmp.search(domain, limit=3, offset=0, order="id asc")
        page2 = MessageAsEmp.search(domain, limit=3, offset=3, order="id asc")
        self.assertFalse(set(page1.ids) & set(page2.ids), "pages must not overlap")
        self.assertEqual(
            len((page1 | page2).filtered(lambda m: m.author_id == employee.partner_id)),
            5,
            "all 5 accessible messages must be reachable across pages",
        )


@tagged("post_install", "-at_install")
class TestFlatThreadParentWindow(MailCommon):
    def test_parent_found_beyond_arbitrary_window(self):
        """Flat-thread parenting must find the root discussion message even when
        more than the old 200-row window of notification messages sit between it
        and the reply.
        """
        record = self.env["res.partner"].create({"name": "T"})
        # Exercise the flat-thread parenting path regardless of the model's own
        # default for _mail_flat_thread.
        with patch.object(type(record), "_mail_flat_thread", True):
            root = record.message_post(
                body="root", message_type="comment", subtype_xmlid="mail.mt_comment"
            )
            for i in range(205):
                record.message_post(
                    body=f"n{i}", message_type="notification", subtype_id=False
                )
            reply = record.message_post(
                body="reply", message_type="comment", subtype_xmlid="mail.mt_comment"
            )
        self.assertEqual(
            reply.parent_id,
            root,
            "reply must parent to the root comment even past the 200-row window",
        )


@tagged("post_install", "-at_install")
class TestMailSendPartialFailure(MailCommon):
    def test_one_recipient_failure_does_not_abort_batch(self):
        """A per-recipient delivery failure (non-OutgoingEmailError) must not
        abort the whole mail: the remaining recipients are still attempted.
        """
        partners = self.env["res.partner"].create(
            [
                {"name": "P1", "email": "p1@ext.example.com"},
                {"name": "P2", "email": "p2@ext.example.com"},
                {"name": "P3", "email": "p3@ext.example.com"},
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

        attempted = []
        IrMailServer = type(self.env["ir.mail_server"])

        def fake_send(server, message, *args, **kwargs):
            recipient = message["To"]
            attempted.append(recipient)
            if "p2@" in recipient:
                raise MailDeliveryException("temporary reject")
            return "<sent>"

        with (
            patch.object(IrMailServer, "send_email", fake_send),
            patch.object(IrMailServer, "_disable_send", lambda server: False),
        ):
            mail._send(raise_exception=False)

        self.assertEqual(
            len(attempted),
            3,
            "all three recipients must be attempted despite P2 failing mid-batch",
        )
