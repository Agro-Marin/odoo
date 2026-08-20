import base64
from collections import Counter
from contextlib import ExitStack
from unittest.mock import patch

from markupsafe import Markup

from odoo.exceptions import AccessError
from odoo.fields import Command
from odoo.tests import new_test_user, tagged, users

from odoo.addons.mail.models import mail_message as mail_message_module
from odoo.addons.mail.tests import common


@tagged("-at_install", "post_install", "mail_message")
class TestMailMessage(common.MailCommon):
    @users("employee")
    def test_can_star_message_without_write_access(self):
        message = (
            self.env["mail.message"]
            .sudo()
            .create(
                {
                    "author_id": self.partner_admin.id,
                    "model": "res.partner",
                    "res_id": self.partner_admin.id,
                    "body": "Hey this is me!",
                }
            )
        )
        message = message.sudo(False)
        self.env.user.group_ids -= self.env.ref("base.group_partner_manager")
        self.assertFalse(message.has_access("write"))
        message.toggle_message_starred()
        self.assertIn(self.env.user.partner_id, message.starred_partner_ids)
        self.env["mail.message"].unstar_all()
        self.assertNotIn(self.env.user.partner_id, message.starred_partner_ids)

    def test_mail_message_read_inexisting(self):
        inexisting_message = (
            self.env["mail.message"].with_user(self.user_employee).browse(-434264)
        )
        self.assertFalse(inexisting_message.exists())
        self.assertTrue(
            inexisting_message.browse().has_access("read"),
            "Should not crash (can read void)",
        )

    def test_mail_message_read_access(self):
        self.env["res.company"].invalidate_model(["name"])
        message_c1 = self._add_messages(
            self.env.company, "Company Note 1", author=self.user_employee.partner_id
        )
        message_c2 = self._add_messages(
            self.company_2, "Company Note 2", author=self.user_employee_c2.partner_id
        )
        search_result = (
            self.env["mail.message"]
            .with_context(allowed_company_ids=[self.env.company.id])
            .with_user(self.user_employee)
            .search([("model", "=", "res.company")])
        )
        self.assertIn(message_c1, search_result)
        self.assertNotIn(message_c2, search_result)

    def test_unlink_failure_message_notify_author(self):
        recipient = new_test_user(self.env, login="Bob", email="invalid_email_addr")
        with self.mock_mail_gateway():
            message = self.env.user.partner_id.message_post(
                body="Hello world!", partner_ids=recipient.partner_id.ids
            )
        self.assertEqual(message.notification_ids.failure_type, "mail_email_invalid")
        self.assertEqual(message.notification_ids.res_partner_id, recipient.partner_id)
        self.assertEqual(message.notification_ids.author_id, self.env.user.partner_id)
        with self.assertBus(
            [
                (self.cr.dbname, "res.partner", recipient.partner_id.id),
                (self.cr.dbname, "res.partner", self.env.user.partner_id.id),
            ],
            [
                {
                    "type": "mail.message/delete",
                    "payload": {"message_ids": [message.id]},
                },
                {
                    "type": "mail.message/delete",
                    "payload": {"message_ids": [message.id]},
                },
            ],
        ):
            message.unlink()


@tagged("-at_install", "post_install", "mail_message")
class TestMailMessageCreateBatch(common.MailCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.thread = cls.env["res.partner"].create({"name": "Thread"})
        cls.subtype_id = cls.env.ref("mail.mt_comment").id
        cls.inline_body = (
            '<p><img src="data:image/png;base64,%s"></p>'
            % base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 40).decode()
        )
        cls.seed_attachment = cls.env["ir.attachment"].create(
            {
                "name": "seed.txt",
                "raw": b"x",
                "res_model": "res.partner",
                "res_id": cls.thread.id,
            }
        )

    def _message_vals(self, count, **extra):
        return [
            {
                "model": "res.partner",
                "res_id": self.thread.id,
                "message_type": "comment",
                "subtype_id": self.subtype_id,
                **extra,
            }
            for _ in range(count)
        ]

    def test_inline_image_keeps_caller_values_intact(self):
        shared = [Command.link(self.seed_attachment.id)]
        vals_list = self._message_vals(3, body=self.inline_body, attachment_ids=shared)
        messages = self.env["mail.message"].create(vals_list)

        self.assertEqual(
            shared,
            [Command.link(self.seed_attachment.id)],
            "create must not append to a list the caller still owns",
        )
        for message in messages:
            self.assertEqual(
                len(message.attachment_ids),
                2,
                "each message keeps the seed attachment and its own inline image only",
            )
            self.assertIn(self.seed_attachment, message.attachment_ids)
        inline = messages.attachment_ids - self.seed_attachment
        self.assertEqual(
            len(inline), 3, "one attachment per message, none shared between them"
        )

    def test_inline_image_accepts_immutable_commands(self):
        message = self.env["mail.message"].create(
            {
                "model": "res.partner",
                "res_id": self.thread.id,
                "message_type": "comment",
                "subtype_id": self.subtype_id,
                "body": self.inline_body,
                "attachment_ids": (Command.link(self.seed_attachment.id),),
            }
        )
        self.assertEqual(len(message.attachment_ids), 2)

    def test_inline_image_follows_the_target_the_message_lands_on(self):
        message = (
            self.env["mail.message"]
            .with_context(default_model="res.partner", default_res_id=self.thread.id)
            .create(
                {
                    "body": self.inline_body,
                    "message_type": "comment",
                    "subtype_id": self.subtype_id,
                }
            )
        )
        self.assertEqual(
            (message.model, message.res_id), ("res.partner", self.thread.id)
        )
        attachment = message.attachment_ids
        self.assertEqual(len(attachment), 1)
        self.assertEqual(
            (attachment.res_model, attachment.res_id),
            ("res.partner", self.thread.id),
            "the inline image belongs to the document, like the message does",
        )

    def test_reply_to_does_not_scale_with_distinct_authors(self):
        authors = self.env["res.partner"].create(
            [
                {"name": "A%s" % i, "email": "a%s@test.example.com" % i}
                for i in range(20)
            ]
        )
        Message = self.env["mail.message"]

        def create_with(author_count):
            vals_list = [
                dict(
                    values,
                    author_id=authors[index % author_count].id,
                    email_from="a%s@test.example.com" % (index % author_count),
                    body="<p>m%s</p>" % index,
                )
                for index, values in enumerate(self._message_vals(20))
            ]
            self.env.flush_all()
            self.env.invalidate_all()
            self.env.cr.flush()
            before = self.cr.sql_log_count
            Message.create(vals_list)
            self.env.flush_all()
            self.env.cr.flush()
            return self.cr.sql_log_count - before

        few = create_with(2)
        many = create_with(20)
        self.assertLessEqual(
            many - few,
            2,
            "the batch pays a bounded number of partner reads, not one per "
            "distinct author (got %s queries for 20 authors against %s for 2)"
            % (many, few),
        )


@tagged("-at_install", "post_install", "mail_message")
class TestMailMessageFetchParams(common.MailCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.thread = cls.env["res.partner"].create({"name": "Thread"})
        cls._add_messages(cls.thread, "hello", count=3, author=cls.partner_employee)

    @users("employee")
    def test_search_term_of_the_wrong_type_is_ignored(self):
        Message = self.env["mail.message"]
        for term in ([], ["x"], {"a": 1}, 5, True):
            with self.subTest(term=term):
                result = Message._message_fetch(
                    domain=None, thread=self.thread, search_term=term
                )
                self.assertNotIn(
                    "count",
                    result,
                    "an unusable search term is no search, so no count is paid for",
                )
        self.assertIn(
            "count",
            Message._message_fetch(
                domain=None, thread=self.thread, search_term="hello"
            ),
        )

    @users("employee")
    def test_is_notification_of_the_wrong_type_is_ignored(self):
        Message = self.env["mail.message"]
        for value in ("true", "false", 1, 0):
            with self.subTest(value=value):
                result = Message._message_fetch(
                    domain=None, thread=self.thread, is_notification=value
                )
                self.assertNotIn(
                    "count",
                    result,
                    "a non-bool filtered nothing, so it must not bill a count either",
                )
        for value in (True, False):
            with self.subTest(value=value):
                self.assertIn(
                    "count",
                    Message._message_fetch(
                        domain=None, thread=self.thread, is_notification=value
                    ),
                )

    @users("employee")
    def test_count_reports_whether_the_cap_bit(self):
        Message = self.env["mail.message"]
        result = Message._message_fetch(
            domain=None, thread=self.thread, search_term="hello"
        )
        self.assertEqual(result["count"], 3)
        self.assertFalse(result["count_is_capped"])

        self.patch(type(Message), "_SEARCH_COUNT_CAP", 2)
        result = Message._message_fetch(
            domain=None, thread=self.thread, search_term="hello"
        )
        self.assertEqual(result["count"], 2)
        self.assertTrue(
            result["count_is_capped"],
            "the client must not have to know the cap to know it was reached",
        )


@tagged("-at_install", "post_install", "mail_message")
class TestMailMessageMarkAllAsRead(common.MailCommon):
    def _make_thread_messages(self, thread, count):
        return (
            self.env["mail.message"]
            .sudo()
            .create(
                [
                    {
                        "model": "res.partner",
                        "res_id": thread.id,
                        "body": "<p>m%s</p>" % index,
                        "message_type": "comment",
                        "subtype_id": self.env.ref("mail.mt_comment").id,
                    }
                    for index in range(count)
                ]
            )
        )

    def _notify(self, messages):
        self.env["mail.notification"].sudo().create(
            [
                {
                    "mail_message_id": message.id,
                    "res_partner_id": self.env.user.partner_id.id,
                    "notification_type": "inbox",
                    "is_read": False,
                }
                for message in messages
            ]
        )
        self.env.flush_all()

    @users("employee")
    def test_mark_all_as_read_never_materialises_a_message(self):
        thread = self.env["res.partner"].sudo().create({"name": "Thread"})
        messages = self._make_thread_messages(thread, 20)
        self._notify(messages[:2])
        domain = [("model", "=", "res.partner"), ("res_id", "=", thread.id)]

        MailMessage = type(self.env["mail.message"])
        calls = Counter()
        patches = []
        for name in ("fetch", "search"):
            real = getattr(MailMessage, name)

            def wrapper(records, *args, _name=name, _real=real, **kwargs):
                calls[_name] += 1
                return _real(records, *args, **kwargs)

            patches.append(patch.object(MailMessage, name, wrapper))

        with ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            marked = self.env["mail.message"].mark_all_as_read(domain)

        self.assertEqual(sorted(marked), sorted(messages[:2].ids))
        self.assertEqual(
            dict(calls),
            {},
            "no mail.message row is read to mark a notification: the domain "
            "becomes a subquery, not a list of ids",
        )

    @users("employee")
    def test_mark_all_as_read_still_refuses_a_restricted_field(self):
        thread = self.env["res.partner"].sudo().create({"name": "Thread"})
        self._notify(self._make_thread_messages(thread, 1))
        self.assertFalse(self.env.user.has_group("base.group_system"))
        with self.assertRaises(AccessError):
            self.env["mail.message"].mark_all_as_read(
                [("tracking_value_ids", "!=", False)]
            )

    @users("employee")
    def test_mark_all_as_read_still_scopes_to_the_domain(self):
        one = self.env["res.partner"].sudo().create({"name": "One"})
        two = self.env["res.partner"].sudo().create({"name": "Two"})
        messages = (
            self.env["mail.message"]
            .sudo()
            .create(
                [
                    {
                        "model": "res.partner",
                        "res_id": thread.id,
                        "body": "<p>m</p>",
                        "message_type": "comment",
                        "subtype_id": self.env.ref("mail.mt_comment").id,
                    }
                    for thread in (one, two)
                ]
            )
        )
        self.env["mail.notification"].sudo().create(
            [
                {
                    "mail_message_id": message.id,
                    "res_partner_id": self.env.user.partner_id.id,
                    "notification_type": "inbox",
                    "is_read": False,
                }
                for message in messages
            ]
        )
        marked = self.env["mail.message"].mark_all_as_read(
            [("model", "=", "res.partner"), ("res_id", "=", one.id)]
        )
        self.assertEqual(marked, messages[0].ids)
        self.assertTrue(messages[0].sudo().notification_ids.is_read)
        self.assertFalse(messages[1].sudo().notification_ids.is_read)


@tagged("-at_install", "post_install", "mail_message")
class TestMailMessageLinkedScan(common.MailCommon):
    def test_linked_scan_parses_only_bodies_that_can_match(self):
        thread = self.env["res.partner"].create({"name": "Thread"})
        target = self.env["mail.message"].create(
            {
                "model": "res.partner",
                "res_id": thread.id,
                "body": "<p>target</p>",
                "message_type": "comment",
                "subtype_id": self.env.ref("mail.mt_comment").id,
            }
        )
        linking = self.env["mail.message"].create(
            {
                "model": "res.partner",
                "res_id": thread.id,
                "body": Markup(
                    '<p><a class="o_message_redirect" data-oe-model="mail.message" '
                    'data-oe-id="%s">go</a></p>' % target.id
                ),
                "message_type": "comment",
                "subtype_id": self.env.ref("mail.mt_comment").id,
            }
        )
        plain = self.env["mail.message"].create(
            {
                "model": "res.partner",
                "res_id": thread.id,
                "body": "<p>nothing to see</p>",
                "message_type": "comment",
                "subtype_id": self.env.ref("mail.mt_comment").id,
            }
        )

        parsed = []
        real_fromstring = mail_message_module.html.fromstring

        def counting_fromstring(body, *args, **kwargs):
            parsed.append(body)
            return real_fromstring(body, *args, **kwargs)

        with patch.object(mail_message_module.html, "fromstring", counting_fromstring):
            found = (linking + plain)._get_linked_message_ids()

        self.assertEqual(found, {linking.id: [target.id]})
        self.assertEqual(
            len(parsed), 1, "only the body that can carry a redirect anchor is parsed"
        )
