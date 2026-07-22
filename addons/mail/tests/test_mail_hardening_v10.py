"""Regression tests for the tenth mail hardening audit.

Each test pins a defect reproduced end to end (real channel records) before
being fixed, so a refactor cannot silently reintroduce it. Coverage:

 - ``discuss.channel._message_receive_bounce`` auto-unfollowed any address that
   bounced ``MAX_BOUNCE_LIMIT`` times regardless of channel type, which for a
   2-person ``chat`` unlinked the correspondent and left a broken 1-member DM
   that the create guard then forbids repairing. Bounce-unfollow is now scoped
   to the channel types that actually allow leaving.
"""

from odoo.tests import tagged

from odoo.addons.mail.tests.common import MailCommon, mail_new_test_user


@tagged("-at_install", "post_install", "mail_hardening_v10")
class TestMessageBatchCreateAccessV10(MailCommon):
    def test_batch_thread_message_create_no_singleton_crash(self):
        """Batch-creating thread messages as a non-superuser must not crash the
        create-access check. ``_get_forbidden_access`` runs
        ``_is_thread_message_visible`` over the whole (multi-record) recordset,
        so resolving ``model``/``res_id``/``message_type`` from ``self`` — rather
        than from each row's ``vals`` — raised ``Expected singleton``.
        """
        channel = self.env["discuss.channel"]._create_channel(
            name="v10-batch", group_id=False
        )
        user = mail_new_test_user(
            self.env, login="v10_batch", name="V10 Batch", groups="base.group_user"
        )
        channel.add_members(partner_ids=user.partner_id.ids)
        subtype_id = self.env.ref("mail.mt_comment").id
        messages = (
            self.env["mail.message"]
            .with_user(user)
            .create(
                [
                    {
                        "model": "discuss.channel",
                        "res_id": channel.id,
                        "body": f"batch {idx}",
                        "message_type": "comment",
                        "subtype_id": subtype_id,
                    }
                    for idx in range(3)
                ]
            )
        )
        self.assertEqual(len(messages), 3)


@tagged("-at_install", "post_install", "mail_hardening_v10")
class TestChannelBounceScopeV10(MailCommon):
    def test_bounce_does_not_break_direct_message(self):
        """A bouncing correspondent must not be unlinked from a 2-person chat."""
        other = mail_new_test_user(
            self.env,
            login="v10_dm",
            name="V10 DM",
            email="v10dm@example.com",
            groups="base.group_user",
        )
        chat = self.env["discuss.channel"]._get_or_create_chat(
            partners_to=other.partner_id.ids
        )
        self.assertEqual(chat.channel_type, "chat")
        members_before = len(chat.channel_member_ids)
        other.partner_id.message_bounce = chat.MAX_BOUNCE_LIMIT
        chat._message_receive_bounce("v10dm@example.com", other.partner_id)
        self.assertEqual(
            len(chat.channel_member_ids),
            members_before,
            "a bounce must not strip a member out of a DM",
        )
        self.assertIn(other.partner_id, chat.channel_member_ids.partner_id)

    def test_bounce_still_unsubscribes_from_broadcast_channel(self):
        """Control: bounce-unfollow is preserved for a regular 'channel'."""
        channel = self.env["discuss.channel"]._create_channel(
            name="v10-bcast", group_id=False
        )
        subscriber = mail_new_test_user(
            self.env,
            login="v10_sub",
            name="V10 Sub",
            email="v10sub@example.com",
            groups="base.group_user",
        )
        channel.add_members(partner_ids=subscriber.partner_id.ids)
        self.assertIn(subscriber.partner_id, channel.channel_member_ids.partner_id)
        subscriber.partner_id.message_bounce = channel.MAX_BOUNCE_LIMIT
        channel._message_receive_bounce("v10sub@example.com", subscriber.partner_id)
        self.assertNotIn(
            subscriber.partner_id,
            channel.channel_member_ids.partner_id,
            "a bounced subscriber must still be unfollowed from a broadcast channel",
        )
