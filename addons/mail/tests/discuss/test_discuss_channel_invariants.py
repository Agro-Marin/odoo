import base64
from collections import Counter
from unittest.mock import patch

from odoo.exceptions import AccessError, UserError
from odoo.tests.common import new_test_user, tagged
from odoo.tools import file_open

from odoo.addons.mail.tests.common import MailCommon
from odoo.addons.mail.tools.discuss import Store


@tagged("post_install", "-at_install")
class TestDiscussChannelInvariants(MailCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Channel = cls.env["discuss.channel"]
        cls.Member = cls.env["discuss.channel.member"]

    def _count_queries(self, func):
        cr = self.env.cr
        count = Counter()
        execute = cr.execute

        def spy(query, params=None, log_exceptions=None):
            count["n"] += 1
            return execute(query, params, log_exceptions=log_exceptions)

        try:
            cr.execute = spy
            func()
        finally:
            cr.execute = execute
        return count["n"]

    def test_copy_drops_the_fields_that_identify_a_sub_channel(self):
        channel = self.Channel._create_channel(name="Parent", group_id=None)
        message = channel.message_post(
            body="seed", message_type="comment", subtype_xmlid="mail.mt_comment"
        )
        sub_channel = channel._create_sub_channel(from_message_id=message.id)
        self.env.flush_all()

        copied = sub_channel.copy()

        self.assertFalse(
            copied.from_message_id,
            "copying the source message violates _from_message_id_unique",
        )
        self.assertFalse(
            copied.parent_channel_id,
            "a copy that keeps its parent silently forks a second thread under it",
        )
        self.assertNotEqual(copied.uuid, sub_channel.uuid)

    def test_sub_channel_bootstrap_does_not_admit_outsiders(self):
        owner = new_test_user(self.env, "inv_owner", groups="base.group_user")
        insider = new_test_user(self.env, "inv_insider", groups="base.group_user")
        outsider = new_test_user(self.env, "inv_outsider", groups="base.group_user")
        parent = self.Channel.with_user(owner)._create_group(
            partners_to=[owner.partner_id.id, insider.partner_id.id], name="Parent"
        )
        sub_channel = parent.with_user(owner)._create_sub_channel(name="Sub")
        self.env.flush_all()
        self.env.invalidate_all()
        self.assertFalse(
            self.Member.search(
                [
                    ("channel_id", "=", sub_channel.id),
                    ("partner_id", "=", insider.partner_id.id),
                ]
            ),
            "the insider must not already be a member of the sub-channel",
        )

        with self.assertRaises(AccessError):
            sub_channel.with_user(insider).add_members(
                partner_ids=[outsider.partner_id.id]
            )

    def test_sub_channel_bootstrap_still_admits_the_parent_s_members(self):
        owner = new_test_user(self.env, "inv_owner2", groups="base.group_user")
        insider = new_test_user(self.env, "inv_insider2", groups="base.group_user")
        parent = self.Channel.with_user(owner)._create_group(
            partners_to=[owner.partner_id.id, insider.partner_id.id], name="Parent"
        )
        sub_channel = parent.with_user(owner)._create_sub_channel(name="Sub")
        self.env.flush_all()
        self.env.invalidate_all()

        member = sub_channel.with_user(insider)._find_or_create_member_for_self()

        self.assertTrue(member, "a parent member must be able to join the sub-channel")
        self.assertEqual(member.partner_id, insider.partner_id)

    def test_create_sub_channel_still_bootstraps_creator_and_author(self):
        owner = new_test_user(self.env, "inv_owner3", groups="base.group_user")
        author = new_test_user(self.env, "inv_author3", groups="base.group_user")
        parent = self.Channel.with_user(owner)._create_group(
            partners_to=[owner.partner_id.id, author.partner_id.id], name="Parent"
        )
        message = parent.with_user(owner).message_post(
            body="seed",
            message_type="comment",
            subtype_xmlid="mail.mt_comment",
            author_id=author.partner_id.id,
        )

        sub_channel = parent.with_user(owner)._create_sub_channel(
            from_message_id=message.id
        )

        self.assertEqual(
            sub_channel.channel_member_ids.partner_id,
            owner.partner_id | author.partner_id,
        )

    def test_channel_fetched_notifies_only_what_it_wrote(self):
        user = new_test_user(self.env, "inv_fetched", groups="base.group_user")
        channel = self.Channel.with_user(user)._get_or_create_chat(
            partners_to=[self.env.user.partner_id.id]
        )
        channel.message_post(
            body="hello", message_type="comment", subtype_xmlid="mail.mt_comment"
        )
        self.env.flush_all()
        cursor = self.env.cr
        execute = cursor.execute
        rows = {}

        def skip_every_row(query, params=None, log_exceptions=None):
            statement = str(query)
            if "UPDATE discuss_channel_member member" in statement:
                result = execute(
                    statement.replace(
                        "FOR NO KEY UPDATE SKIP LOCKED",
                        "AND FALSE FOR NO KEY UPDATE SKIP LOCKED",
                    ),
                    params,
                    log_exceptions=log_exceptions,
                )
                rows["count"] = cursor.rowcount
                return result
            return execute(query, params, log_exceptions=log_exceptions)

        sent = Counter()
        bus_send = type(self.Channel)._bus_send

        def spy(records, notification_type, message, /, **kwargs):
            if notification_type == "discuss.channel.member/fetched":
                sent["n"] += 1
            return bus_send(records, notification_type, message, **kwargs)

        try:
            cursor.execute = skip_every_row
            with patch.object(type(self.Channel), "_bus_send", spy):
                channel.with_user(user).channel_fetched()
        finally:
            cursor.execute = execute

        self.assertEqual(rows["count"], 0, "the UPDATE must have written nothing")
        self.assertEqual(
            sent["n"], 0, "a read marker was broadcast for a row that was not written"
        )

    def test_channel_fetched_still_notifies_what_it_did_write(self):
        user = new_test_user(self.env, "inv_fetched2", groups="base.group_user")
        channel = self.Channel.with_user(user)._get_or_create_chat(
            partners_to=[self.env.user.partner_id.id]
        )
        channel.message_post(
            body="hello", message_type="comment", subtype_xmlid="mail.mt_comment"
        )
        self.env.flush_all()
        last_message = channel._get_last_messages()
        sent = Counter()
        bus_send = type(self.Channel)._bus_send

        def spy(records, notification_type, payload, /, **kwargs):
            if notification_type == "discuss.channel.member/fetched":
                sent["n"] += 1
            return bus_send(records, notification_type, payload, **kwargs)

        with patch.object(type(self.Channel), "_bus_send", spy):
            channel.with_user(user).channel_fetched()

        member = self.Member.search(
            [("channel_id", "=", channel.id), ("partner_id", "=", user.partner_id.id)]
        )
        self.assertEqual(sent["n"], 1)
        self.assertEqual(member.fetched_message_id, last_message)

    def test_avatar_cache_key_busts_without_reading_the_avatar(self):
        with file_open("base/static/img/res_company_logo.png", "rb") as file:
            first = base64.b64encode(file.read())
        with file_open("base/static/description/icon.png", "rb") as file:
            second = base64.b64encode(file.read())
        channel = self.Channel._create_channel(name="Avatar", group_id=None)

        channel.write({"image_128": first})
        channel.flush_recordset()
        channel.invalidate_recordset()
        with_first = channel.avatar_cache_key
        channel.write({"image_128": second})
        channel.flush_recordset()
        channel.invalidate_recordset()
        with_second = channel.avatar_cache_key
        channel.write({"image_128": False})
        channel.flush_recordset()
        channel.invalidate_recordset()
        generated = channel.avatar_cache_key

        self.assertNotEqual(with_first, with_second, "a new image must bust the cache")
        self.assertNotEqual(with_second, generated, "clearing it must bust the cache")
        channel.invalidate_recordset()
        self.assertEqual(
            generated,
            channel.avatar_cache_key,
            "a generated avatar never changes, so neither may its key",
        )

    def test_avatar_cache_key_does_not_read_image_128(self):
        with file_open("base/static/img/res_company_logo.png", "rb") as file:
            image = base64.b64encode(file.read())
        channels = self.Channel
        for index in range(5):
            channels |= self.Channel._create_channel(
                name=f"Avatar {index}", group_id=None
            )
        channels.write({"image_128": image})
        channels.flush_recordset()
        self.env.invalidate_all()

        channels.mapped("avatar_cache_key")

        for channel in channels:
            self.assertFalse(
                "image_128" in self.env.cache.get_fields(channel),
                "deriving the cache key must not materialise the avatar",
            )

    def test_avatar_cache_key_is_distinct_per_channel_and_absent_for_chats(self):
        channels = self.Channel
        for index in range(5):
            channels |= self.Channel._create_channel(name=f"Key {index}", group_id=None)
        user = new_test_user(self.env, "inv_avatar", groups="base.group_user")
        chat = self.Channel._get_or_create_chat(partners_to=[user.partner_id.id])

        self.assertEqual(len(set(channels.mapped("avatar_cache_key"))), 5)
        self.assertEqual(chat.avatar_cache_key, "no-avatar")

    def test_notify_members_joined_serialises_the_channel_once(self):
        partners = self.env["res.partner"].create(
            [{"name": f"Joiner {index}"} for index in range(10)]
        )
        channel = self.Channel._create_channel(name="Joined", group_id=None)
        members = self.Member.create(
            [
                {"channel_id": channel.id, "partner_id": partner.id}
                for partner in partners
            ]
        )
        calls = Counter()
        to_store = type(self.Channel)._to_store

        def spy(records, store, fields, **kwargs):
            calls["n"] += 1
            return to_store(records, store, fields, **kwargs)

        self.env.invalidate_all()
        with patch.object(type(self.Channel), "_to_store", spy):
            channel._notify_members_joined(members, False)

        self.assertLessEqual(
            calls["n"],
            2,
            "the channel payload varies only with Store.Target.is_current_user, "
            "so ten recipients need at most two serialisations",
        )

    def test_write_accepts_an_unchanged_immutable_field(self):
        channel = self.Channel._create_channel(name="Immutable", group_id=None)
        other = self.Channel._create_channel(name="Other", group_id=None)
        sub_channel = channel._create_sub_channel(name="Sub")

        sub_channel.write({"name": "Renamed", "parent_channel_id": channel.id})

        self.assertEqual(sub_channel.name, "Renamed")
        with self.assertRaises(UserError):
            sub_channel.write({"parent_channel_id": other.id})
        with self.assertRaises(UserError):
            sub_channel.write({"parent_channel_id": False})

    def test_create_channel_refuses_a_group_that_does_not_resolve(self):
        with self.assertRaises(UserError):
            self.Channel._create_channel(name="Stale", group_id=999999999)

        restricted = self.Channel._create_channel(
            name="Restricted", group_id=self.env.ref("base.group_user").id
        )
        public = self.Channel._create_channel(name="Public", group_id=None)

        self.assertEqual(restricted.group_public_id, self.env.ref("base.group_user"))
        self.assertFalse(public.group_public_id)

    def test_invitation_token_is_not_guessable(self):
        channel = self.Channel._create_channel(name="Token", group_id=None)

        self.assertGreaterEqual(
            len(channel.uuid), 22, "a bearer token wants at least 128 bits"
        )
        self.assertLessEqual(len(channel.uuid), 50, "the column is size=50")
        self.assertEqual(
            len({self.Channel._default_uuid() for _ in range(100)}),
            100,
            "tokens must not repeat",
        )

    def test_auto_subscribe_does_no_work_without_groups(self):
        channel = self.Channel._create_channel(name="NoGroups", group_id=None)

        queries = self._count_queries(channel._subscribe_users_automatically)

        self.assertEqual(
            queries, 0, "every channel creation paid for an empty member create"
        )

    def test_auto_subscribe_still_subscribes_a_group(self):
        group = self.env["res.groups"].create({"name": "Auto Subscribe"})
        user = new_test_user(self.env, "inv_subscribe", groups="base.group_user")
        user.group_ids = [(4, group.id)]
        channel = self.Channel._create_channel(name="WithGroups", group_id=None)

        channel.write({"group_ids": [(4, group.id)]})

        self.assertIn(user.partner_id, channel.channel_member_ids.partner_id)

    def test_notify_get_recipients_declares_its_singleton(self):
        first = self.Channel._create_channel(name="Recipients A", group_id=None)
        second = self.Channel._create_channel(name="Recipients B", group_id=None)
        message = first.message_post(
            body="hello", message_type="comment", subtype_xmlid="mail.mt_comment"
        )

        with self.assertRaises(ValueError):
            (first | second)._notify_get_recipients(
                message, msg_vals={"message_type": "comment"}
            )

    def test_allowed_message_partner_ids_filters_by_group_and_keeps_order(self):
        group = self.env["res.groups"].create({"name": "Allowed"})
        internal = self.env.ref("base.group_user")
        insiders = self.env["res.users"].create(
            [
                {
                    "name": f"Insider {index}",
                    "login": f"inv_allowed_{index}",
                    "email": f"inv_allowed_{index}@example.com",
                    "group_ids": [(6, 0, [internal.id, group.id])],
                }
                for index in range(3)
            ]
        )
        outsider = self.env["res.users"].create(
            {
                "name": "Outsider",
                "login": "inv_allowed_out",
                "email": "inv_allowed_out@example.com",
                "group_ids": [(6, 0, [internal.id])],
            }
        )
        no_user = self.env["res.partner"].create({"name": "No User"})
        channel = self.Channel._create_channel(name="Allowed", group_id=group.id)
        requested = list(reversed(insiders.partner_id.ids)) + [
            outsider.partner_id.id,
            no_user.id,
        ]

        allowed = channel._get_allowed_message_partner_ids(requested)

        self.assertEqual(
            allowed,
            list(reversed(insiders.partner_id.ids)),
            "the caller's order must survive the group filter",
        )

    def test_allowed_message_partner_ids_drops_unreadable_mentions(self):
        group = self.env["res.groups"].create({"name": "Unreadable"})
        internal = self.env.ref("base.group_user")
        poster = self.env["res.users"].create(
            {
                "name": "Poster",
                "login": "inv_unreadable_poster",
                "email": "inv_unreadable_poster@example.com",
                "group_ids": [(6, 0, [internal.id, group.id])],
            }
        )
        other_company = self.env["res.company"].create({"name": "Elsewhere"})
        unreadable = self.env["res.partner"].create(
            {"name": "Elsewhere Contact", "company_id": other_company.id}
        )
        channel = self.Channel._create_channel(name="Unreadable", group_id=group.id)
        self.env.flush_all()
        self.env.invalidate_all()

        allowed = channel.with_user(poster)._get_allowed_message_partner_ids(
            [poster.partner_id.id, unreadable.id]
        )

        self.assertEqual(allowed, [poster.partner_id.id])

    def test_allowed_message_partner_ids_declares_its_singleton(self):
        first = self.Channel._create_channel(name="Allowed A", group_id=None)
        second = self.Channel._create_channel(name="Allowed B", group_id=None)
        partner = self.env["res.partner"].create({"name": "Mentioned"})

        with self.assertRaises(ValueError):
            (first | second)._get_allowed_message_partner_ids([partner.id])

    def test_invitation_values_resolve_the_base_url_once(self):
        channel = self.Channel._create_channel(name="Invitations", group_id=None)
        calls = Counter()
        config = self.env["ir.config_parameter"]
        get_base_url = type(config).get_base_url

        def spy(records):
            calls["n"] += 1
            return get_base_url(records)

        addresses = channel._get_uninvited_emails(
            [f"invitee{index}@example.com" for index in range(10)]
        )
        with patch.object(type(config), "get_base_url", spy):
            values = channel._get_invitation_mail_values(addresses)

        self.assertEqual(len(values), 10)
        self.assertEqual(calls["n"], 1, "the base URL does not vary per recipient")
        self.assertEqual(
            len({value["subject"] for value in values}),
            1,
            "neither does the subject",
        )

    def test_self_member_lookups_are_the_computed_field(self):
        user = new_test_user(self.env, "inv_self", groups="base.group_user")
        channel = self.Channel.with_user(user)._create_group(
            partners_to=[user.partner_id.id], name="Self"
        )
        as_user = self.env(user=user)["discuss.channel"].browse(channel.id)

        searched = self.env(user=user)["discuss.channel.member"].search(
            [("channel_id", "=", channel.id), ("is_self", "=", True)]
        )

        self.assertEqual(as_user.self_member_id, searched)
        self.assertEqual(as_user._find_or_create_member_for_self(), searched)

    def test_find_or_create_member_for_self_is_idempotent_for_a_guest(self):
        channel = self.Channel._create_channel(name="Guest Self", group_id=None)
        guest = self.env["mail.guest"].create({"name": "Guesty"})
        as_guest = self.env(
            user=self.env.ref("base.public_user"),
            context=dict(self.env.context, guest=guest),
        )["discuss.channel"].browse(channel.id)

        first = as_guest._find_or_create_member_for_self()
        second = as_guest._find_or_create_member_for_self()

        self.assertTrue(first)
        self.assertEqual(first, second, "a second call must not create a second row")
        self.assertEqual(first.guest_id, guest)

    def test_inviting_new_members_to_a_call_does_not_query_per_channel(self):
        user = new_test_user(self.env, "inv_call", groups="base.group_user")
        channels = self.Channel
        new_members_by_channel = {}
        for index in range(6):
            partners = self.env["res.partner"].create(
                [{"name": f"Callee {index}-{other}"} for other in range(2)]
            )
            channel = self.Channel.with_user(user)._create_group(
                partners_to=[user.partner_id.id], name=f"Call {index}"
            )
            channels |= channel
            new_members_by_channel[channel] = channel._add_members(partners=partners)
        self.env.invalidate_all()

        queries = self._count_queries(
            lambda: channels._invite_new_members_to_call(new_members_by_channel)
        )

        self.assertLess(
            queries,
            6,
            "the self-member lookup batches across the recordset, so six channels "
            "must not cost six queries",
        )

    def test_channel_pin_toggles_and_is_idempotent(self):
        user = new_test_user(self.env, "inv_pin", groups="base.group_user")
        other = new_test_user(self.env, "inv_pin_other", groups="base.group_user")
        chat = self.Channel.with_user(user)._get_or_create_chat(
            partners_to=[other.partner_id.id]
        )
        as_user = self.env(user=user)["discuss.channel"].browse(chat.id)
        member = self.Member.search(
            [("channel_id", "=", chat.id), ("partner_id", "=", user.partner_id.id)]
        )

        def pinned_after(pinned):
            as_user.channel_pin(pinned)
            self.env.flush_all()
            member.invalidate_recordset()
            return member.is_pinned

        self.assertFalse(pinned_after(False))
        self.assertFalse(pinned_after(False), "unpinning twice must stay unpinned")
        self.assertTrue(pinned_after(True))

    def test_channel_payload_is_unchanged_by_the_avatar_key_derivation(self):
        channel = self.Channel._create_channel(name="Payload", group_id=None)
        self.env.invalidate_all()

        payload = Store().add(channel).get_result()

        self.assertIn("avatar_cache_key", payload["discuss.channel"][0])
        self.assertTrue(payload["discuss.channel"][0]["avatar_cache_key"])
