from unittest.mock import patch

from odoo.tests import tagged, users
from odoo.tools import mute_logger

from odoo.addons.mail.tests.common import MailCommon


@tagged("mail_thread", "mail_base")
class TestBaseIdSpaces(MailCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.record = cls.env["mail.test.ticket"].create(
            {"name": "Origin", "email_from": "origin.customer@test.example.com"}
        )

    @users("employee")
    def test_partner_find_from_emails_keys_by_record_id(self):
        record = self.env["mail.test.ticket"].browse(self.record.id)
        draft = self.env["mail.test.ticket"].new(origin=record)
        self.assertNotEqual(
            list(draft.ids),
            list(draft._ids),
            "the premise: .ids resolves a new record to its origin, .id does not",
        )
        found = draft._partner_find_from_emails(
            {draft: ["someone@test.example.com"]}, no_create=True
        )
        self.assertEqual(list(found), [draft.id])
        self.assertEqual(
            draft._partner_find_from_emails_single(
                ["someone@test.example.com"], no_create=True
            ),
            self.env["res.partner"],
        )

    @users("employee")
    def test_a_name_only_input_still_receives_the_record_values(self):
        record = self.env["mail.test.ticket.mc"].create(
            {"name": "Company Bound", "email_from": "bound@test.example.com"}
        )
        self.assertTrue(record.company_id)
        for name in ("Name Only Person", '"Bad Address" <not-an-email>'):
            with self.subTest(name=name):
                partner = record._partner_find_from_emails_single(
                    [name], customer_information={name: {"phone": "+32 470 12 34 56"}}
                )
                self.assertTrue(partner)
                self.assertEqual(partner.company_id, record.company_id)
                self.assertEqual(partner.phone, "+32 470 12 34 56")

    @users("employee")
    def test_suggested_recipients_on_a_draft_of_a_stored_record(self):
        record = self.env["mail.test.ticket"].browse(self.record.id)
        draft = self.env["mail.test.ticket"].new(origin=record)
        suggested = draft._message_get_suggested_recipients_batch()
        self.assertEqual(list(suggested), [draft.id])
        self.assertEqual(draft._message_get_suggested_recipients(), suggested[draft.id])

    @users("employee")
    def test_every_per_record_mapping_shares_one_id_space(self):
        record = self.env["mail.test.ticket"].browse(self.record.id)
        for scope in (record, self.env["mail.test.ticket"].new(origin=record)):
            expected = [scope.id]
            for name in (
                "_mail_get_partners",
                "_mail_get_alias_domains",
                "_mail_get_companies",
                "_message_get_default_recipients",
                "_notify_get_reply_to",
            ):
                self.assertEqual(
                    list(getattr(scope, name)()),
                    expected,
                    f"{name} must key on record.id like every sibling",
                )

    @users("employee")
    def test_reply_to_per_author_matches_the_unmemoised_result(self):
        records = self.env["mail.test.ticket"].create(
            [
                {"name": f"Ticket {i}", "email_from": f"t{i}@test.example.com"}
                for i in range(5)
            ]
        )
        authors = (
            self.env["res.partner"]
            .sudo()
            .create(
                [
                    {"name": f"Author {i}", "email": f"a{i}@test.example.com"}
                    for i in range(3)
                ]
            )
        )
        pairs = {(a.id, f"a{i}@test.example.com") for i, a in enumerate(authors)}
        got = records._notify_get_reply_to_per_author(pairs)
        addresses = records._notify_get_reply_to_addresses()
        keys = records._notify_reply_to_scope()[2]
        expected = {}
        for author_id, author_email in pairs:
            per_record = dict.fromkeys(keys, author_email)
            for res_id, address in addresses.items():
                per_record[res_id] = records._notify_get_reply_to_formatted_email(
                    address, author_id=author_id
                )
            expected[(author_id, author_email)] = per_record
        self.assertEqual(got, expected)

    @users("employee")
    def test_a_partner_whose_address_only_differs_in_spacing_is_kept(self):
        partner = (
            self.env["res.partner"]
            .sudo()
            .create({"name": "Unparseable", "email": "not-an-address"})
        )
        record = self.env["mail.test.ticket"].create(
            {
                "name": "Spacing",
                "customer_id": partner.id,
                "email_from": "  not-an-address  ",
            }
        )
        defaults = record._message_get_default_recipients()[record.id]
        self.assertEqual(defaults["partner_ids"], [partner.id])
        self.assertFalse(defaults["email_to"])

    @mute_logger("odoo.addons.mail.models.base")
    def test_a_misdeclared_partner_field_is_reported_not_swallowed(self):
        model = self.env.registry["mail.test.ticket"]
        declared = model._mail_partner_fields
        model._mail_partner_fields = ("customer_id", "name", "no_such_field")
        self.env.registry.clear_cache()
        try:
            with self.assertLogs(
                "odoo.addons.mail.models.base", level="WARNING"
            ) as capture:
                fnames = self.env["mail.test.ticket"]._mail_get_partner_fields()
            self.assertEqual(fnames, ["customer_id"])
            message = "\n".join(capture.output)
            self.assertIn("'name'", message)
            self.assertIn("'no_such_field'", message)
        finally:
            model._mail_partner_fields = declared
            self.env.registry.clear_cache()


@tagged("mail_thread", "mail_base")
class TestBaseSuggestedMessageSort(MailCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.record = cls.env["mail.test.ticket"].create(
            {"name": "Sorted", "email_from": "sorted@test.example.com"}
        )

    def _post_comment(self, body, **kwargs):
        return self.record.message_post(
            body=body,
            message_type="comment",
            subtype_xmlid="mail.mt_comment",
            **kwargs,
        )

    def test_a_message_without_a_date_does_not_break_the_recipient_list(self):
        self._post_comment("dated")
        undated = self._post_comment("undated", date=False)
        self.env.flush_all()
        self.assertFalse(undated.date, "the premise: mail.message.date is nullable")
        suggested = self.record._message_get_suggested_recipients(reply_discussion=True)
        self.assertIsInstance(suggested, list)
        self.record._message_get_suggested_recipients_batch(reply_discussion=True)

    def test_an_undated_message_never_outranks_a_dated_one(self):
        dated = self._post_comment("dated")
        self._post_comment("undated", date=False)
        self.env.flush_all()
        messages = self.record._mail_get_thread_messages()[self.record.id]
        ordered = self.record._sort_suggested_messages(messages)
        self.assertEqual(
            ordered[0],
            dated,
            "a message carrying no date must not be taken as the latest",
        )

    def test_the_comment_subtype_list_never_carries_a_falsy_id(self):
        self.assertTrue(all(self.record._mail_suggested_message_subtype_ids()))
        untyped = self.env["mail.message"].create(
            {
                "model": self.record._name,
                "res_id": self.record.id,
                "message_type": "comment",
                "body": "no subtype",
            }
        )
        self.assertFalse(untyped.subtype_id.id)
        real = type(self.env["ir.model.data"])._xmlid_to_res_id

        def missing_xmlid(model, xmlid, *args, **kwargs):
            if xmlid == "mail.mt_comment":
                return 0
            return real(model, xmlid, *args, **kwargs)

        with patch.object(
            type(self.env["ir.model.data"]), "_xmlid_to_res_id", missing_xmlid
        ):
            subtype_ids = self.record._mail_suggested_message_subtype_ids()
            self.assertTrue(
                all(subtype_ids),
                "a resolved-to-zero xmlid must not enter the list: False == 0, so "
                "it would make every subtype-less message pass as a comment",
            )
            self.assertNotIn(untyped, self.record._sort_suggested_messages(untyped))

    def test_banned_email_keys_are_deduplicated(self):
        seen = []
        real = type(self.env["mail.alias.domain"])._find_aliases

        def capture(domains, email_list):
            seen.append(list(email_list))
            return real(domains, email_list)

        with patch.object(
            type(self.env["mail.alias.domain"]), "_find_aliases", capture
        ):
            self.record._mail_get_banned_emails(
                ["dup@test.example.com"] * 5 + ["other@test.example.com"]
            )
        self.assertTrue(seen, "the alias lookup must have been reached")
        passed = seen[0]
        self.assertEqual(
            len(passed),
            len(set(passed)),
            "the alias search must be handed each address once, not once per "
            f"occurrence; got {passed}",
        )
