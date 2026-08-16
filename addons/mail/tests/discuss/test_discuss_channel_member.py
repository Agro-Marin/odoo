from datetime import datetime, timedelta
from unittest.mock import patch

from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import new_test_user, tagged

from odoo.addons.mail.tests.common import MailCommon


@tagged("post_install", "-at_install")
class TestDiscussChannelMember(MailCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.secret_group = cls.env["res.groups"].create(
            {
                "name": "Secret User Group",
            }
        )
        cls.env["ir.model.data"].create(
            {
                "name": "secret_group",
                "module": "mail",
                "model": cls.secret_group._name,
                "res_id": cls.secret_group.id,
            }
        )
        cls.user_1 = new_test_user(
            cls.env,
            login="user_1",
            name="User 1",
            groups="base.group_user,mail.secret_group",
        )
        cls.user_2 = new_test_user(
            cls.env,
            login="user_2",
            name="User 2",
            groups="base.group_user,mail.secret_group",
        )
        cls.user_3 = new_test_user(
            cls.env,
            login="user_3",
            name="User 3",
            groups="base.group_user,mail.secret_group",
        )
        cls.user_portal = new_test_user(
            cls.env, login="user_portal", name="User Portal", groups="base.group_portal"
        )
        cls.user_public = new_test_user(
            cls.env, login="user_public", name="User Public", groups="base.group_public"
        )

        cls.group = cls.env["discuss.channel"].create(
            {
                "name": "Group",
                "channel_type": "group",
            }
        )
        cls.group_restricted_channel = cls.env["discuss.channel"].create(
            {
                "name": "Group restricted channel",
                "channel_type": "channel",
                "group_public_id": cls.secret_group.id,
            }
        )
        cls.public_channel = cls.env["discuss.channel"]._create_channel(
            group_id=None, name="Public channel of user 1"
        )
        (
            cls.group | cls.group_restricted_channel | cls.public_channel
        ).channel_member_ids.unlink()

    def test_group_01(self):
        res = self.env["discuss.channel.member"].search(
            [("channel_id", "=", self.group.id)]
        )
        self.assertFalse(res)

        self.group.with_user(self.user_1).sudo()._add_members(users=self.user_1)
        res = self.env["discuss.channel.member"].search(
            [("channel_id", "=", self.group.id)]
        )
        self.assertEqual(res.partner_id, self.user_1.partner_id)

        with self.assertRaises(AccessError):
            self.group.with_user(self.user_2)._add_members(users=self.user_2)

        with self.assertRaises(AccessError):
            self.env["discuss.channel.member"].with_user(self.user_2).create(
                {
                    "partner_id": self.user_2.partner_id.id,
                    "channel_id": self.group.id,
                }
            )

        channel_member = (
            self.env["discuss.channel.member"]
            .with_user(self.user_2)
            .search([("is_self", "=", True)])[0]
        )
        with self.assertRaises(AccessError):
            channel_member.channel_id = self.group.id
        with self.assertRaises(AccessError):
            channel_member.write({"channel_id": self.group.id})

        with self.assertRaises(AccessError):
            channel_member.sudo().channel_id = self.group.id

        channel_member_1 = self.env["discuss.channel.member"].search(
            [
                ("channel_id", "=", self.group.id),
                ("partner_id", "=", self.user_1.partner_id.id),
            ]
        )
        with self.assertRaises(AccessError):
            channel_member_1.with_user(self.user_2).partner_id = self.user_2.partner_id
        self.assertEqual(channel_member_1.partner_id, self.user_1.partner_id)

        with self.assertRaises(AccessError):
            channel_member_1.with_user(
                self.user_2
            ).sudo().partner_id = self.user_2.partner_id

    def test_group_members(self):
        self.group.with_user(self.user_1).sudo()._add_members(users=self.user_1)
        channel_members = self.env["discuss.channel.member"].search(
            [("channel_id", "=", self.group.id)]
        )
        self.assertEqual(len(channel_members), 1)

        with self.assertRaises(AccessError):
            self.env["discuss.channel.member"].with_user(self.user_2).create(
                {
                    "partner_id": self.user_portal.partner_id.id,
                    "channel_id": self.group.id,
                }
            )

        self.env["discuss.channel.member"].with_user(self.user_1).create(
            {
                "partner_id": self.user_portal.partner_id.id,
                "channel_id": self.group.id,
            }
        )
        channel_members = self.env["discuss.channel.member"].search(
            [("channel_id", "=", self.group.id)]
        )
        self.assertEqual(
            channel_members.mapped("partner_id"),
            self.user_1.partner_id | self.user_portal.partner_id,
        )

        channel_member_1 = self.env["discuss.channel.member"].search(
            [
                ("channel_id", "=", self.group.id),
                ("partner_id", "=", self.user_1.partner_id.id),
            ]
        )
        channel_member_3 = self.env["discuss.channel.member"].search(
            [
                ("channel_id", "=", self.group.id),
                ("partner_id", "=", self.user_portal.partner_id.id),
            ]
        )
        channel_member_3.with_user(self.user_portal).custom_channel_name = "Test"
        with self.assertRaises(AccessError):
            channel_member_1.with_user(self.user_2).custom_channel_name = "Blabla"
        self.assertNotEqual(channel_member_1.custom_channel_name, "Blabla")

    def test_group_invite(self):
        self.group.with_user(self.user_1).sudo()._add_members(users=self.user_1)
        channel_members = self.env["discuss.channel.member"].search(
            [("channel_id", "=", self.group.id)]
        )
        self.assertEqual(channel_members.mapped("partner_id"), self.user_1.partner_id)

        with self.assertRaises(AccessError):
            self.group.with_user(self.user_2)._add_members(users=self.user_portal)
        channel_members = self.env["discuss.channel.member"].search(
            [("channel_id", "=", self.group.id)]
        )
        self.assertEqual(channel_members.mapped("partner_id"), self.user_1.partner_id)

        self.group.with_user(self.user_1)._add_members(users=self.user_portal)
        channel_members = self.env["discuss.channel.member"].search(
            [("channel_id", "=", self.group.id)]
        )
        self.assertEqual(
            channel_members.mapped("partner_id"),
            self.user_1.partner_id | self.user_portal.partner_id,
        )

    def test_group_leave(self):
        self.group.with_user(self.user_1).sudo()._add_members(users=self.user_1)
        self.group.with_user(self.user_portal).sudo()._add_members(
            users=self.user_portal
        )
        channel_members = self.env["discuss.channel.member"].search(
            [("channel_id", "=", self.group.id)]
        )
        self.assertEqual(len(channel_members), 2)

        with self.assertRaises(AccessError):
            channel_members.with_user(self.user_2).unlink()

        with self.assertRaises(AccessError):
            channel_members.with_user(self.user_portal).unlink()

    def test_group_subchannel_join(self):
        self.group.add_members((self.user_1 | self.user_2).partner_id.ids)
        group_subchannel = self.group.with_user(self.user_1)._create_sub_channel()
        group_subchannel.with_user(self.user_2).add_members(self.user_2.partner_id.id)
        self.assertEqual(
            group_subchannel.channel_member_ids.partner_id,
            (self.user_1 | self.user_2).partner_id,
        )

    def test_group_restricted_channel(self):
        channel_members = self.env["discuss.channel.member"].search(
            [("channel_id", "=", self.group_restricted_channel.id)]
        )
        self.assertFalse(channel_members)

        self.group_restricted_channel.with_user(self.user_1)._add_members(
            users=self.user_1
        )
        channel_members = self.env["discuss.channel.member"].search(
            [("channel_id", "=", self.group_restricted_channel.id)]
        )
        self.assertEqual(channel_members.mapped("partner_id"), self.user_1.partner_id)

        with self.assertRaises(AccessError):
            self.group_restricted_channel.with_user(self.user_portal)._add_members(
                users=self.user_portal
            )

        channel_members = self.env["discuss.channel.member"].search(
            [("channel_id", "=", self.group_restricted_channel.id)]
        )
        with self.assertRaises(AccessError):
            channel_members.with_user(
                self.user_portal
            ).partner_id = self.user_portal.partner_id

        channel_members = self.env["discuss.channel.member"].search(
            [("channel_id", "=", self.group_restricted_channel.id)]
        )
        self.assertEqual(channel_members.mapped("partner_id"), self.user_1.partner_id)

        self.group_restricted_channel.with_user(self.user_1)._add_members(
            users=self.user_portal
        )
        channel_members = self.env["discuss.channel.member"].search(
            [("channel_id", "=", self.group_restricted_channel.id)]
        )
        self.assertEqual(
            channel_members.mapped("partner_id"),
            self.user_1.partner_id | self.user_portal.partner_id,
        )

        self.group_restricted_channel.with_user(self.user_1)._add_members(
            users=self.user_2
        )
        channel_members = self.env["discuss.channel.member"].search(
            [("channel_id", "=", self.group_restricted_channel.id)]
        )
        self.assertEqual(
            channel_members.mapped("partner_id"),
            self.user_1.partner_id
            | self.user_2.partner_id
            | self.user_portal.partner_id,
        )

    def test_public_channel(self):
        channel_members = self.env["discuss.channel.member"].search(
            [("channel_id", "=", self.public_channel.id)]
        )
        self.assertFalse(channel_members)

        self.public_channel.with_user(self.user_1)._add_members(users=self.user_1)
        channel_members = self.env["discuss.channel.member"].search(
            [("channel_id", "=", self.public_channel.id)]
        )
        self.assertEqual(channel_members.mapped("partner_id"), self.user_1.partner_id)

        self.public_channel.with_user(self.user_2)._add_members(users=self.user_2)
        channel_members = self.env["discuss.channel.member"].search(
            [("channel_id", "=", self.public_channel.id)]
        )
        self.assertEqual(
            channel_members.mapped("partner_id"),
            self.user_1.partner_id | self.user_2.partner_id,
        )

        self.public_channel.with_user(self.user_portal)._add_members(
            users=self.user_portal
        )
        with self.assertRaises(ValidationError):
            self.public_channel.with_user(self.user_public)._add_members(
                users=self.user_public
            )

    def test_channel_member_invite_with_guest(self):
        guest = self.env["mail.guest"].create({"name": "Guest"})
        partner = self.env["res.partner"].create(
            {
                "name": "ToInvite",
                "active": True,
                "type": "contact",
                "user_ids": self.user_1,
            }
        )
        self.public_channel._add_members(guests=guest)
        data = self.env["res.partner"].search_for_channel_invite(
            partner.name, channel_id=self.public_channel.id
        )["store_data"]
        self.assertEqual(len(data["res.partner"]), 1)
        self.assertEqual(data["res.partner"][0]["id"], partner.id)

    def test_unread_counter_with_message_post(self):
        channel_as_user_1 = (
            self.env["discuss.channel"]
            .with_user(self.user_1)
            ._create_channel(group_id=None, name="Public channel")
        )
        channel_as_user_1.with_user(self.user_1)._add_members(users=self.user_1)
        channel_as_user_1.with_user(self.user_1)._add_members(users=self.user_2)
        channel_1_rel_user_2 = self.env["discuss.channel.member"].search(
            [
                ("channel_id", "=", channel_as_user_1.id),
                ("partner_id", "=", self.user_2.partner_id.id),
            ]
        )
        self.assertEqual(
            channel_1_rel_user_2.message_unread_counter,
            0,
            "should not have unread message initially as notification type is ignored",
        )

        channel_as_user_1.message_post(
            body="Test", message_type="comment", subtype_xmlid="mail.mt_comment"
        )
        channel_1_rel_user_2 = self.env["discuss.channel.member"].search(
            [
                ("channel_id", "=", channel_as_user_1.id),
                ("partner_id", "=", self.user_2.partner_id.id),
            ]
        )
        self.assertEqual(
            channel_1_rel_user_2.message_unread_counter,
            1,
            "should have 1 unread message after someone else posted a message",
        )

    def test_write_skips_unread_recompute_for_unrelated_fields(self):
        channel = (
            self.env["discuss.channel"]
            .with_user(self.user_1)
            ._create_channel(group_id=None, name="unread perf channel")
        )
        channel._add_members(users=self.user_1 | self.user_2)
        member = self.env["discuss.channel.member"].search(
            [
                ("channel_id", "=", channel.id),
                ("partner_id", "=", self.user_2.partner_id.id),
            ]
        )
        channel.message_post(
            body="m", message_type="comment", subtype_xmlid="mail.mt_comment"
        )

        member_model = type(member)
        original_compute = member_model._compute_message_unread
        calls = []

        def _counting(records):
            calls.append(records.ids)
            return original_compute(records)

        with patch.object(member_model, "_compute_message_unread", _counting):
            member.write({"mute_until_dt": datetime.now() + timedelta(days=1)})
            self.assertEqual(
                calls, [], "unrelated member write recomputed the unread counter"
            )
            member.write({"new_message_separator": 1})
            self.assertTrue(
                calls,
                "writing new_message_separator must recompute the unread counter",
            )

    def test_unread_counter_with_message_post_multi_channel(self):
        channel_1_as_user_1 = (
            self.env["discuss.channel"]
            .with_user(self.user_1)
            ._create_channel(group_id=None, name="wololo channel")
        )
        channel_2_as_user_2 = (
            self.env["discuss.channel"]
            .with_user(self.user_2)
            ._create_channel(group_id=None, name="walala channel")
        )
        channel_1_as_user_1._add_members(users=self.user_2)
        channel_2_as_user_2._add_members(users=self.user_1)
        channel_2_as_user_2._add_members(users=self.user_3)
        channel_1_as_user_1.message_post(
            body="Test", message_type="comment", subtype_xmlid="mail.mt_comment"
        )
        channel_1_as_user_1.message_post(
            body="Test 2", message_type="comment", subtype_xmlid="mail.mt_comment"
        )
        channel_2_as_user_2.message_post(
            body="Test", message_type="comment", subtype_xmlid="mail.mt_comment"
        )
        members = self.env["discuss.channel.member"].search(
            [("channel_id", "in", (channel_1_as_user_1 + channel_2_as_user_2).ids)],
            order="id",
        )
        self.assertEqual(
            members.mapped("message_unread_counter"),
            [
                0,
                0,
                2,
                1,
                1,
            ],
        )
