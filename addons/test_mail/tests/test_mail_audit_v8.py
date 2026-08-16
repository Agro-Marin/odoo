# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Regression tests for the eighth mail audit.

Pins six defects found in ``mail.thread`` and the guarantee that replaced a
seventh, retracted claim:

* a tracking message is authored by the user who made *that* change, not by
  whoever wrote first in the transaction;
* ``message_parse`` keeps the sender's recipient order, all the way to the
  ``incoming_email_to`` stored on the message;
* a falsy ``body`` posts an empty message, not the text ``"False"``;
* ``_message_update_content`` with a reduced ``attachment_ids`` drops the
  attachments the caller left out;
* the attachment format error names the value that was rejected;
* an abstract model is refused by the router instead of reaching a table that
  does not exist;
* ``notify_cancel_by_type`` sees notifications written earlier in the same
  transaction;
* linking an unreadable attachment is refused by the ORM (the invariant that
  makes a model-level ownership check unnecessary).
"""

import ast

from markupsafe import Markup

from odoo.exceptions import AccessError
from odoo.tests import tagged, users

from odoo.addons.mail.tests.common import MailCommon


@tagged("post_install", "-at_install", "mail_audit_v8")
class TestMailThreadAuditV8(MailCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.v8_alice, cls.v8_bob = cls.env["res.users"].create(
            [
                {
                    "name": "V8 Alice",
                    "login": "v8_alice",
                    "email": "v8.alice@test.example.com",
                    "group_ids": [(4, cls.env.ref("base.group_user").id)],
                },
                {
                    "name": "V8 Bob",
                    "login": "v8_bob",
                    "email": "v8.bob@test.example.com",
                    "group_ids": [(4, cls.env.ref("base.group_user").id)],
                },
            ]
        )
        cls.v8_customer = cls.env["res.partner"].create(
            {"name": "V8 Customer", "email": "v8.customer@test.example.com"}
        )

    def _tracking_author(self, record):
        return (
            self.env["mail.message"]
            .sudo()
            .search(
                [
                    ("model", "=", record._name),
                    ("res_id", "=", record.id),
                    ("tracking_value_ids", "!=", False),
                ]
            )
            .author_id
        )

    def _settle(self):
        self.env.flush_all()
        self.env.cr.precommit.run()
        self.env.flush_all()

    # ------------------------------------------------------------------
    # tracking authorship is per writer, not per transaction
    # ------------------------------------------------------------------

    def test_tracking_author_is_the_writer(self):
        for first, second in (
            (self.v8_alice, self.v8_bob),
            (self.v8_bob, self.v8_alice),
        ):
            with self.subTest(first=first.login):
                one, two = self.env["mail.performance.tracking"].create(
                    [{"name": "V8 one"}, {"name": "V8 two"}]
                )
                self._settle()
                one.with_user(first).write({"field_0": "first"})
                two.with_user(second).write({"field_0": "second"})
                self._settle()
                self.assertEqual(self._tracking_author(one), first.partner_id)
                self.assertEqual(self._tracking_author(two), second.partner_id)

    def test_tracking_runs_under_each_writer(self):
        """``_message_track`` is entered once per writing user."""
        seen_uids = []
        original = type(self.env["mail.thread"])._message_track

        def spy(records, fields_iter, initial_values_dict):
            seen_uids.append(records.env.uid)
            return original(records, fields_iter, initial_values_dict)

        self.patch(type(self.env["mail.thread"]), "_message_track", spy)
        one, two = self.env["mail.performance.tracking"].create(
            [{"name": "V8 lang one"}, {"name": "V8 lang two"}]
        )
        self._settle()
        one.with_user(self.v8_alice).write({"field_0": "a"})
        two.with_user(self.v8_bob).write({"field_0": "b"})
        self._settle()
        self.assertEqual(set(seen_uids), {self.v8_alice.id, self.v8_bob.id})

    def test_tracking_single_writer_is_unchanged(self):
        one, two = self.env["mail.performance.tracking"].create(
            [{"name": "V8 solo one"}, {"name": "V8 solo two"}]
        )
        self._settle()
        (one + two).with_user(self.v8_alice).write({"field_0": "x"})
        self._settle()
        self.assertEqual(self._tracking_author(one), self.v8_alice.partner_id)
        self.assertEqual(self._tracking_author(two), self.v8_alice.partner_id)

    def test_tracking_log_message_reaches_every_writer_group(self):
        """``_track_set_log_message`` survives the per-writer split."""
        one, two = self.env["mail.performance.tracking"].create(
            [{"name": "V8 body one"}, {"name": "V8 body two"}]
        )
        self._settle()
        one.with_user(self.v8_alice)._track_set_log_message(Markup("<p>logged</p>"))
        two.with_user(self.v8_bob)._track_set_log_message(Markup("<p>logged</p>"))
        one.with_user(self.v8_alice).write({"field_0": "a"})
        two.with_user(self.v8_bob).write({"field_0": "b"})
        self._settle()
        for record in (one, two):
            messages = (
                self.env["mail.message"]
                .sudo()
                .search([("model", "=", record._name), ("res_id", "=", record.id)])
            )
            self.assertIn("logged", "".join(messages.mapped("body")))

    # ------------------------------------------------------------------
    # gateway keeps the sender's recipient order
    # ------------------------------------------------------------------

    RAW_ORDER = (
        "Message-Id: <v8-order@test.example.com>\r\n"
        "From: v8.sender@test.example.com\r\n"
        "To: aaa@t.example.com, bbb@t.example.com, ccc@t.example.com, "
        "ddd@t.example.com, eee@t.example.com\r\n"
        "Cc: fff@t.example.com, ggg@t.example.com\r\n"
        "Subject: v8 order\r\n\r\nbody\r\n"
    )
    ORDERED_TO = [
        "aaa@t.example.com",
        "bbb@t.example.com",
        "ccc@t.example.com",
        "ddd@t.example.com",
        "eee@t.example.com",
    ]

    def _parse(self, raw):
        import email
        import email.policy

        return self.env["mail.thread"].message_parse(
            email.message_from_string(raw, policy=email.policy.SMTP)
        )

    def test_message_parse_keeps_recipient_order(self):
        parsed = self._parse(self.RAW_ORDER)
        self.assertEqual(parsed["to"].split(","), self.ORDERED_TO)
        self.assertEqual(
            parsed["recipients"].split(","),
            self.ORDERED_TO + ["fff@t.example.com", "ggg@t.example.com"],
        )
        self.assertEqual(parsed["to_filtered"].split(","), self.ORDERED_TO)

    def test_message_parse_still_deduplicates(self):
        raw = (
            "Message-Id: <v8-dup@test.example.com>\r\n"
            "From: v8.sender@test.example.com\r\n"
            "Delivered-To: aaa@t.example.com\r\n"
            "To: aaa@t.example.com, bbb@t.example.com\r\n"
            "Cc: bbb@t.example.com\r\n"
            "Subject: v8 dup\r\n\r\nbody\r\n"
        )
        parsed = self._parse(raw)
        self.assertEqual(
            parsed["to"].split(","), ["aaa@t.example.com", "bbb@t.example.com"]
        )
        self.assertEqual(
            parsed["recipients"].split(","),
            ["aaa@t.example.com", "bbb@t.example.com"],
        )

    def test_gateway_stores_recipient_order(self):
        alias = self.env["mail.alias"].create(
            {
                "alias_name": "v8-gw",
                "alias_model_id": self.env["ir.model"]._get_id("mail.test.gateway"),
                "alias_contact": "everyone",
            }
        )
        self.env.flush_all()
        raw = (
            "Message-Id: <v8-gw@test.example.com>\r\n"
            "From: v8.sender@test.example.com\r\n"
            f"To: {', '.join(self.ORDERED_TO)}, {alias.alias_full_name}\r\n"
            "Subject: v8 gateway\r\n\r\nbody\r\n"
        )
        res_id = self.env["mail.thread"].message_process("mail.test.gateway", raw)
        record = self.env["mail.test.gateway"].browse(res_id)
        message = record.message_ids.sorted("id")[-1]
        self.assertEqual(message.incoming_email_to.split(","), self.ORDERED_TO)

    # ------------------------------------------------------------------
    # a falsy body is empty, not the word "False"
    # ------------------------------------------------------------------

    def test_falsy_body_is_empty(self):
        record = self.env["mail.test.simple"].create({"name": "V8 body"})
        for value in (None, False):
            with self.subTest(value=value):
                self.assertFalse(
                    record.message_post(body=value, message_type="comment").body
                )
                self.assertFalse(record._message_log(body=value).body)
                self.assertFalse(
                    self.env["mail.thread"]
                    .message_notify(body=value, partner_ids=self.v8_customer.ids)
                    .body
                )

    def test_falsy_body_on_update_matches_empty_string(self):
        """``body=False`` clears like ``body=""``; it never stores "False"."""
        record = self.env["mail.test.simple"].create({"name": "V8 body upd"})
        cleared, blanked = (
            record.message_post(body="original", message_type="comment")
            for _ in range(2)
        )
        record._message_update_content(cleared, body=False)
        record._message_update_content(blanked, body="")
        self.assertEqual(cleared.body, blanked.body)
        self.assertNotIn("False", cleared.body)

    def test_truthy_body_is_unchanged(self):
        record = self.env["mail.test.simple"].create({"name": "V8 body ok"})
        self.assertIn(
            "&lt;b&gt;",
            record.message_post(body="a<b>c", message_type="comment").body,
        )
        self.assertIn(
            "<b>c</b>",
            record.message_post(body=Markup("a<b>c</b>"), message_type="comment").body,
        )
        self.assertIn("0", record.message_post(body=0, message_type="comment").body)

    # ------------------------------------------------------------------
    # _message_update_content: attachment_ids adds, [] voids
    #
    # Pinned because the audit read the add-only behaviour as a defect. It is
    # the contract: ``TestAPI.test_message_update_content`` asserts the union,
    # and the web client only ever sends the full set or ``[]``.
    # ------------------------------------------------------------------

    def _draft_attachment(self, name):
        return self.env["ir.attachment"].create(
            {
                "name": name,
                "raw": b"x",
                "res_model": "mail.compose.message",
                "res_id": 0,
            }
        )

    def test_update_content_attachment_ids_add(self):
        record = self.env["mail.test.simple"].create({"name": "V8 att"})
        first = self._draft_attachment("v8-a1.txt")
        message = record.message_post(
            body="one", message_type="comment", attachment_ids=[first.id]
        )
        second = self._draft_attachment("v8-a2.txt")
        record._message_update_content(
            message, body="edited", attachment_ids=[second.id]
        )
        self.assertEqual(message.attachment_ids, first + second)

    def test_update_content_empty_list_clears(self):
        record = self.env["mail.test.simple"].create({"name": "V8 att clear"})
        first = self._draft_attachment("v8-c1.txt")
        message = record.message_post(
            body="one", message_type="comment", attachment_ids=[first.id]
        )
        record._message_update_content(message, body="edited", attachment_ids=[])
        self.assertFalse(message.attachment_ids)

    # ------------------------------------------------------------------
    # _message_notify_batch derives the document-shaped fields per record
    # ------------------------------------------------------------------

    def test_notify_batch_refuses_document_fields_per_call(self):
        """One value cannot stand for every document in the batch."""
        records = self.env["mail.test.simple"].create(
            [{"name": "V8 nb1"}, {"name": "V8 nb2"}]
        )
        bodies = dict.fromkeys(records.ids, "x")
        for field, value in (
            ("reply_to", "one@test.example.com"),
            ("record_company_id", self.env.company.id),
            ("record_alias_domain_id", self.env.company.alias_domain_id.id),
        ):
            with self.subTest(field=field), self.assertRaises(ValueError) as capture:
                records._message_notify_batch(
                    bodies, partner_ids=self.v8_customer.ids, **{field: value}
                )
            self.assertIn(field, str(capture.exception))

    def test_notify_batch_derives_document_fields_per_record(self):
        records = self.env["mail.test.simple"].create(
            [{"name": "V8 nb3"}, {"name": "V8 nb4"}]
        )
        messages = records._message_notify_batch(
            {record.id: f"body {record.id}" for record in records},
            subjects={record.id: f"subject {record.id}" for record in records},
            partner_ids=self.v8_customer.ids,
        )
        self.assertEqual(len(messages), 2)
        self.assertEqual(set(messages.mapped("res_id")), set(records.ids))
        self.assertEqual(
            len(set(messages.mapped("message_id"))), 2, "message_id is per message"
        )
        for message in messages:
            self.assertIn(str(message.res_id), message.body)
            self.assertEqual(message.subject, f"subject {message.res_id}")

    def test_notify_singleton_still_takes_document_fields(self):
        """message_notify is a batch of one, so mail.activity's hoist still works."""
        record = self.env["mail.test.simple"].create({"name": "V8 nb5"})
        message = record.message_notify(
            body="x",
            partner_ids=self.v8_customer.ids,
            reply_to="pinned@test.example.com",
            record_company_id=self.env.company.id,
        )
        self.assertEqual(message.reply_to, "pinned@test.example.com")
        self.assertEqual(message.record_company_id, self.env.company)

    # ------------------------------------------------------------------
    # the attachment format error names the rejected value
    # ------------------------------------------------------------------

    def test_attachment_format_error_names_attachments(self):
        record = self.env["mail.test.simple"].create({"name": "V8 err"})
        with self.assertRaises(ValueError) as capture:
            record.message_post(body="x", attachments=["not-a-tuple"])
        self.assertIn("not-a-tuple", str(capture.exception))

        with self.assertRaises(ValueError) as capture:
            self.env["mail.thread"].message_notify(
                body="x",
                partner_ids=self.v8_customer.ids,
                attachments=["not-a-tuple"],
            )
        self.assertIn("not-a-tuple", str(capture.exception))

    # ------------------------------------------------------------------
    # abstract models are refused by the router
    # ------------------------------------------------------------------

    def test_abstract_model_is_refused(self):
        raw = (
            "Message-Id: <v8-abs@test.example.com>\r\n"
            "From: v8.sender@test.example.com\r\n"
            "To: dest@test.example.com\r\nSubject: p\r\n\r\nbody\r\n"
        )
        with self.assertRaises(ValueError) as capture:
            self.env["mail.thread"].message_process("mail.thread", raw)
        self.assertIn("mail.thread", str(capture.exception))

    def _models_offered_by(self, model_name, field_name):
        domain = (
            self.env[model_name]
            ._fields[field_name]
            .get_description(self.env, ["domain"])["domain"]
        )
        if isinstance(domain, str):
            domain = ast.literal_eval(domain)
        return self.env["ir.model"].search(domain)

    def test_abstract_models_are_not_offered_as_alias_targets(self):
        offered = self._models_offered_by("mail.alias", "alias_model_id")
        self.assertTrue(offered)
        self.assertFalse(
            [model.model for model in offered if self.env[model.model]._abstract]
        )

    def test_abstract_models_are_not_offered_to_fetchmail(self):
        offered = self._models_offered_by("fetchmail.server", "object_id")
        self.assertTrue(offered)
        self.assertFalse(
            [model.model for model in offered if self.env[model.model]._abstract]
        )

    # ------------------------------------------------------------------
    # cancel-by-type sees this transaction's writes
    # ------------------------------------------------------------------

    def test_cancel_by_type_sees_unflushed_status(self):
        record = self.env["mail.test.simple"].create({"name": "V8 cancel"})
        record.message_subscribe(partner_ids=self.v8_customer.ids)
        message = record.with_user(self.v8_bob).message_post(
            body="x", message_type="comment", subtype_xmlid="mail.mt_comment"
        )
        notifications = message.sudo().notification_ids.filtered(
            lambda notif: notif.notification_type == "email"
        )
        self.assertTrue(notifications)
        notifications.write({"notification_status": "exception"})
        # deliberately not flushed
        record.with_user(self.v8_bob).notify_cancel_by_type("email")
        self.env.flush_all()
        self.assertEqual(set(notifications.mapped("notification_status")), {"canceled"})

    # ------------------------------------------------------------------
    # the ORM refuses to link an attachment the poster cannot read
    # ------------------------------------------------------------------

    def test_unreadable_attachment_cannot_be_linked(self):
        secret = (
            self.env["ir.attachment"]
            .with_user(self.v8_alice)
            .create({"name": "v8-secret.txt", "raw": b"top-secret"})
        )
        self.env.flush_all()
        record = self.env["mail.test.simple"].create({"name": "V8 grab"})
        with self.assertRaises(AccessError):
            record.with_user(self.v8_bob).message_post(
                body="grab", message_type="comment", attachment_ids=[secret.id]
            )
        self.env.invalidate_all()
        with self.assertRaises(AccessError):
            secret.with_user(self.v8_bob).datas

    # ------------------------------------------------------------------
    # boolean search fields negate correctly (no defect; pins the behaviour)
    # ------------------------------------------------------------------

    @users("v8_alice")
    def test_boolean_search_fields_negate(self):
        Record = self.env["mail.test.simple"]
        followed = Record.create({"name": "V8 followed"})
        other = Record.create({"name": "V8 not followed"})
        followed.message_subscribe(partner_ids=self.env.user.partner_id.ids)
        other.message_unsubscribe(partner_ids=self.env.user.partner_id.ids)
        self.env.flush_all()
        pair = followed + other
        for domain, expected in (
            ([("message_is_follower", "=", True)], followed),
            ([("message_is_follower", "=", False)], other),
            ([("message_is_follower", "!=", True)], other),
        ):
            with self.subTest(domain=domain):
                self.assertEqual(
                    Record.search([("id", "in", pair.ids)] + domain), expected
                )
