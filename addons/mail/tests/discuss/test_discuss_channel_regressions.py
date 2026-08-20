from markupsafe import Markup

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import new_test_user, tagged

from odoo.addons.mail.tests.common import MailCommon


@tagged("post_install", "-at_install")
class TestDiscussChannelRegressions(MailCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.owner = new_test_user(cls.env, login="chan_owner", groups="base.group_user")
        cls.outsider = new_test_user(
            cls.env, login="chan_sysadmin", groups="base.group_system"
        )
        cls.invitee_1 = new_test_user(
            cls.env, login="chan_i1", groups="base.group_user"
        )
        cls.invitee_2 = new_test_user(
            cls.env, login="chan_i2", groups="base.group_user"
        )
        cls.invitee_3 = new_test_user(
            cls.env, login="chan_i3", groups="base.group_user"
        )
        cls.channel = (
            cls.env["discuss.channel"]
            .with_user(cls.owner)
            ._create_channel(name="Regressions", group_id=None)
        )

    def _channel_messages(self, channel):
        return self.env["mail.message"].search(
            [("model", "=", "discuss.channel"), ("res_id", "=", channel.id)],
            order="id",
        )

    def test_pin_by_non_member_admin_names_the_actor(self):
        message = self.channel.with_user(self.owner).message_post(
            body="pin me", message_type="comment", subtype_xmlid="mail.mt_comment"
        )
        channel = self.channel.with_user(self.outsider)
        self.assertFalse(channel.self_member_id)
        channel.set_message_pin(message.id, True)
        notification = self._channel_messages(self.channel)[-1]
        body = notification.body.striptags()
        self.assertNotIn("False", body)
        self.assertIn(self.outsider.display_name, body)

    def test_member_html_link_without_persona_flag(self):
        member = self.channel.channel_member_ids[0]
        link = member._get_html_link()
        self.assertIn("discuss.channel.member", link)
        self.assertIn(str(member.id), link)

    def test_member_html_link_title_never_false(self):
        self.assertEqual(self.env["discuss.channel.member"]._get_html_link_title(), "")

    def test_guest_leave_notification_has_an_author(self):
        group = (
            self.env["discuss.channel"]
            .with_user(self.owner)
            ._create_group(partners_to=self.owner.partner_id.ids, name="Guest group")
        )
        guest = self.env["mail.guest"].create({"name": "Casper"})
        group.sudo()._add_members(guests=guest, post_joined_message=False)
        before = self._channel_messages(group)
        group.with_user(self.env.ref("base.public_user")).with_context(
            guest=guest
        ).action_unfollow()
        posted = self._channel_messages(group) - before
        self.assertEqual(len(posted), 1)
        self.assertEqual(posted.author_guest_id, guest)
        self.assertIn("left the channel", posted.body.striptags())

    def test_add_members_posts_one_message_for_the_whole_invite(self):
        group = (
            self.env["discuss.channel"]
            .with_user(self.owner)
            ._create_group(partners_to=self.owner.partner_id.ids, name="Invite group")
        )
        before = self._channel_messages(group)
        invitees = (
            self.invitee_1.partner_id
            | self.invitee_2.partner_id
            | self.invitee_3.partner_id
        )
        group.with_user(self.owner)._add_members(partners=invitees)
        posted = self._channel_messages(group) - before
        self.assertEqual(len(posted), 1)
        body = posted.body.striptags()
        for invitee in invitees:
            self.assertIn(invitee.name, body)

    def test_add_members_self_join_keeps_its_own_message(self):
        group = (
            self.env["discuss.channel"]
            .with_user(self.owner)
            ._create_group(partners_to=self.owner.partner_id.ids, name="Join group")
        )
        guest = self.env["mail.guest"].create({"name": "Walk-in"})
        before = self._channel_messages(group)
        group.with_user(self.env.ref("base.public_user")).sudo().with_context(
            guest=guest
        )._add_members(guests=guest)
        posted = self._channel_messages(group) - before
        self.assertEqual(len(posted), 1)
        self.assertIn("joined the channel", posted.body.striptags())
        self.assertNotIn("invited", posted.body.striptags())

    def test_create_rejects_malformed_member_commands(self):
        for payload in ([self.invitee_1.partner_id.id], [(3, 1)], ["nope"], [(6, 0)]):
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                self.env["discuss.channel"].create(
                    {
                        "name": "bad",
                        "channel_type": "group",
                        "channel_partner_ids": payload,
                    }
                )

    def test_create_still_accepts_valid_member_commands(self):
        channel = self.env["discuss.channel"].create(
            {
                "name": "good",
                "channel_type": "group",
                "channel_partner_ids": [(4, self.invitee_1.partner_id.id)],
            }
        )
        self.assertIn(self.invitee_1.partner_id, channel.channel_partner_ids)

    def test_chat_left_with_one_member_can_regain_a_second(self):
        other = self.env["res.partner"].create({"name": "Gone", "email": "g@x.com"})
        chat = (
            self.env["discuss.channel"]
            .with_user(self.owner)
            ._get_or_create_chat(partners_to=other.ids)
        )
        self.assertEqual(len(chat.channel_member_ids), 2)
        other.unlink()
        chat.invalidate_recordset()
        self.assertEqual(len(chat.sudo().channel_member_ids), 1)
        chat.sudo()._add_members(partners=self.invitee_1.partner_id)
        self.assertEqual(len(chat.sudo().channel_member_ids), 2)

    def test_chat_still_refuses_a_third_member(self):
        chat = (
            self.env["discuss.channel"]
            .with_user(self.owner)
            ._get_or_create_chat(partners_to=self.invitee_1.partner_id.ids)
        )
        with self.assertRaises(UserError):
            chat.sudo()._add_members(partners=self.invitee_2.partner_id)

    def test_expired_mutes_are_cleared(self):
        member = self.channel.channel_member_ids[0]
        member.mute_until_dt = "2020-01-01 00:00:00"
        self.env["discuss.channel.member"]._cleanup_expired_mutes()
        self.assertFalse(member.mute_until_dt)

    def test_is_member_search_stays_in_sql(self):
        query = (
            self.env["discuss.channel"]
            .with_user(self.owner)
            ._search([("is_member", "=", True)])
        )
        sql = str(query.select())
        self.assertIn("discuss_channel_member", sql)
        self.assertIn(self.channel.id, list(query))

    def test_is_member_search_matches_nothing_without_a_persona(self):
        public = self.env.ref("base.public_user")
        query = (
            self.env["discuss.channel"]
            .with_user(public)
            ._search([("is_member", "=", True)])
        )
        self.assertFalse(list(query))

    def test_channel_pin_resolves_a_guest_member(self):
        group = (
            self.env["discuss.channel"]
            .with_user(self.owner)
            ._create_group(partners_to=self.owner.partner_id.ids, name="Pin group")
        )
        guest = self.env["mail.guest"].create({"name": "Pinner"})
        group.sudo()._add_members(guests=guest, post_joined_message=False)
        member = group.sudo().channel_member_ids.filtered(lambda m: m.guest_id == guest)
        self.assertFalse(member.unpin_dt)
        group.with_user(self.env.ref("base.public_user")).with_context(
            guest=guest
        ).channel_pin(False)
        member.invalidate_recordset()
        self.assertTrue(member.unpin_dt)

    def test_action_unfollow_resolves_a_guest_member(self):
        group = (
            self.env["discuss.channel"]
            .with_user(self.owner)
            ._create_group(partners_to=self.owner.partner_id.ids, name="Leave group")
        )
        guest = self.env["mail.guest"].create({"name": "Leaver"})
        group.sudo()._add_members(guests=guest, post_joined_message=False)
        member = group.sudo().channel_member_ids.filtered(lambda m: m.guest_id == guest)
        group.with_user(self.env.ref("base.public_user")).with_context(
            guest=guest
        ).action_unfollow()
        self.assertFalse(member.exists())

    def test_channel_fetched_updates_every_member_in_one_pass(self):
        groups = (
            self.env["discuss.channel"]
            .with_user(self.owner)
            .create([{"name": f"fetch {i}", "channel_type": "group"} for i in range(3)])
        )
        groups._add_members(
            partners=self.invitee_1.partner_id, post_joined_message=False
        )
        for group in groups:
            group.with_user(self.owner).message_post(
                body="hi", message_type="comment", subtype_xmlid="mail.mt_comment"
            )
        groups.with_user(self.invitee_1).channel_fetched()
        members = self.env["discuss.channel.member"].search(
            [
                ("channel_id", "in", groups.ids),
                ("partner_id", "=", self.invitee_1.partner_id.id),
            ]
        )
        self.assertEqual(len(members), 3)
        for member in members:
            self.assertTrue(member.fetched_message_id)

    def test_member_write_prunes_unaffected_sync_fields(self):
        member = self.channel.channel_member_ids[0]
        sync = member._get_write_sync_field_names({"unpin_dt": False})
        names = [member._get_store_field_name(fd) for fd in sync[None]]
        self.assertIn("unpin_dt", names)
        self.assertNotIn("message_unread_counter", names)
        sync = member._get_write_sync_field_names({"new_message_separator": 1})
        names = [member._get_store_field_name(fd) for fd in sync[None]]
        self.assertIn("message_unread_counter", names)

    def test_channel_and_member_share_one_sync_contract(self):
        for model in ("discuss.channel", "discuss.channel.member"):
            with self.subTest(model=model):
                mapping = self.env[model]._sync_field_names()
                self.assertIsInstance(mapping, dict)
                self.assertIn(None, mapping)

    def test_structural_write_requires_membership(self):
        with self.assertRaises(AccessError):
            self.channel.with_user(self.invitee_1).write({"name": "hijacked"})

    def test_guest_join_notification_is_attributed_to_the_inviter(self):
        group = (
            self.env["discuss.channel"]
            .with_user(self.owner)
            ._create_group(partners_to=self.owner.partner_id.ids, name="Attrib group")
        )
        guest = self.env["mail.guest"].create({"name": "Newcomer"})
        before = self._channel_messages(group)
        group.with_user(self.owner)._add_members(guests=guest)
        posted = self._channel_messages(group) - before
        self.assertEqual(len(posted), 1)
        self.assertEqual(posted.author_id, self.owner.partner_id)
        self.assertIn("Newcomer", posted.body.striptags())

    def test_post_joined_message_body_is_escaped(self):
        evil = new_test_user(
            self.env,
            login="evil_member",
            name="<script>alert(1)</script>",
            groups="base.group_user",
        )
        group = (
            self.env["discuss.channel"]
            .with_user(self.owner)
            ._create_group(partners_to=self.owner.partner_id.ids, name="Escape group")
        )
        before = self._channel_messages(group)
        group.with_user(self.owner)._add_members(partners=evil.partner_id)
        posted = self._channel_messages(group) - before
        self.assertNotIn("<script>", posted.body)
        self.assertIsInstance(posted.body, Markup)
