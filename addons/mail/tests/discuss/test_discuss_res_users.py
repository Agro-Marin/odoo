from odoo import Command
from odoo.tests.common import tagged

from odoo.addons.mail.tests.common import MailCommon, mail_new_test_user


@tagged("post_install", "-at_install")
class TestDiscussResUsers(MailCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.channel_group = cls.env["res.groups"].create({"name": "Channel Group"})
        cls.implying_group = cls.env["res.groups"].create(
            {
                "name": "Implies Channel Group",
                "implied_ids": [Command.set(cls.channel_group.ids)],
            }
        )
        cls.group_channel = cls.env["discuss.channel"].create(
            {
                "name": "Group Channel",
                "channel_type": "channel",
                "group_public_id": cls.channel_group.id,
                "group_ids": [Command.set(cls.channel_group.ids)],
            }
        )

    def _is_member(self, user):
        return bool(
            self.env["discuss.channel.member"]
            .sudo()
            .search_count(
                [
                    ("channel_id", "=", self.group_channel.id),
                    ("partner_id", "=", user.partner_id.id),
                ]
            )
        )

    def test_group_write_accepts_a_plain_list_of_ids(self):
        user = mail_new_test_user(
            self.env, login="bare_ids", name="Bare Ids", groups="base.group_user"
        )
        internal_group = self.env.ref("base.group_user")

        user.write({"group_ids": [internal_group.id, self.channel_group.id]})

        self.assertIn(self.channel_group, user.group_ids)
        self.assertTrue(self._is_member(user), "and the subscription still happened")

    def test_group_write_subscribes_for_every_command_shape(self):
        internal_group = self.env.ref("base.group_user")
        for label, value in (
            ("link", [Command.link(self.channel_group.id)]),
            ("set", [Command.set([self.channel_group.id])]),
        ):
            with self.subTest(command=label):
                user = mail_new_test_user(
                    self.env,
                    login="cmd_%s" % label,
                    name="Cmd %s" % label,
                    groups="base.group_user",
                )
                self.assertFalse(self._is_member(user))
                user.write({"group_ids": value})
                self.assertTrue(self._is_member(user))
                user.write({"group_ids": [Command.link(internal_group.id)]})

    def test_group_write_subscribes_through_an_implied_group(self):
        user = mail_new_test_user(
            self.env, login="implied_chan", name="Implied", groups="base.group_user"
        )
        self.assertFalse(self._is_member(user))

        user.write({"group_ids": [Command.link(self.implying_group.id)]})

        self.assertNotIn(self.channel_group, user.group_ids, "held by implication only")
        self.assertIn(self.channel_group, user.all_group_ids)
        self.assertTrue(self._is_member(user))

    def test_archiving_a_user_leaves_only_the_public_channels(self):
        user = mail_new_test_user(
            self.env,
            login="archived_member",
            name="Archived",
            groups="base.group_user",
        )
        user.write({"group_ids": [Command.link(self.channel_group.id)]})
        public_channel = self.env["discuss.channel"].create(
            {
                "name": "Public Channel",
                "channel_type": "channel",
                "group_public_id": False,
            }
        )
        public_channel.add_members(partner_ids=user.partner_id.ids)
        self.assertTrue(self._is_member(user))

        user.action_archive()

        self.assertFalse(self._is_member(user), "the group-restricted one is dropped")
        self.assertTrue(
            self.env["discuss.channel.member"]
            .sudo()
            .search_count(
                [
                    ("channel_id", "=", public_channel.id),
                    ("partner_id", "=", user.partner_id.id),
                ]
            ),
            "the public one is kept",
        )
