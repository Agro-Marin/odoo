from unittest.mock import patch

from odoo.tests import tagged

from odoo.addons.mail.tests.common import MailCommon


@tagged("mail_hardening", "post_install", "-at_install")
class BaseHardeningV21(MailCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env["res.partner"].create(
            {"name": "Customer V21", "email": "customer.v21@test.example.com"}
        )
        cls.record = cls.env["mail.test.ticket"].create(
            {"name": "Ticket V21", "customer_id": cls.customer.id}
        )

    @staticmethod
    def _mailboxes(suggestions):
        return sorted(entry["email"] or entry["name"] for entry in suggestions)

    def _count_queries(self, func):
        counter = [0]
        execute = self.env.cr.execute

        def counting(*args, **kwargs):
            counter[0] += 1
            return execute(*args, **kwargs)

        self.env.cr.execute = counting
        try:
            func()
        finally:
            self.env.cr.execute = execute
        return counter[0]


class TestFieldPathAcrossManyRecordsV21(BaseHardeningV21):
    """Each value is formatted with the record that carries it."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.currency_alpha = cls.env["res.currency"].create(
            {"name": "V2A", "symbol": "α", "rounding": 0.01}
        )
        cls.currency_beta = cls.env["res.currency"].create(
            {"name": "V2B", "symbol": "β", "rounding": 0.01}
        )
        cls.parent = cls.env["mail.test.track.all"].create({"name": "Parent V21"})

    def _add_children(self, *currencies):
        return self.env["mail.test.track.all.o2m"].create(
            [
                {
                    "name": f"Child {index}",
                    "mail_track_all_id": self.parent.id,
                    "currency_id": currency.id,
                    "monetary_field": 10.0 * (index + 1),
                }
                for index, currency in enumerate(currencies)
            ]
        )

    def test_two_currencies_do_not_raise_out_of_a_public_api(self):
        self._add_children(self.currency_alpha, self.currency_beta)
        # Before: ValueError('Expected singleton: res.currency(x, y)'). The whole
        # traversed recordset was handed to the formatter, so reading the currency
        # off it answered with the union of both.
        rendered = self.parent._find_value_from_field_path(
            "one2many_field.monetary_field"
        )
        self.assertIn("α", rendered)
        self.assertIn("β", rendered, "the second child's own currency, not the first's")

    def test_one_currency_is_still_rendered_once_per_record(self):
        self._add_children(self.currency_alpha, self.currency_alpha)
        rendered = self.parent._find_value_from_field_path(
            "one2many_field.monetary_field"
        )
        self.assertEqual(rendered.count("α"), 2)

    def test_a_zero_is_still_rendered(self):
        record = self.env["mail.test.track.all"].create(
            {"name": "Zero V21", "float_field": 0.0, "integer_field": 0}
        )
        # '0 == False', so a membership test against (False, None, '') would drop
        # these; the identity comparisons have to stay.
        self.assertEqual(record._find_value_from_field_path("integer_field"), "0")
        self.assertEqual(record._find_value_from_field_path("float_field"), "0.00")

    def test_a_falsy_value_is_still_dropped(self):
        children = self._add_children(self.currency_alpha, self.currency_alpha)
        children[0].name = False
        self.assertEqual(
            self.parent._find_value_from_field_path("one2many_field.name"), "Child 1"
        )

    def test_a_void_recordset_is_still_a_path_validator(self):
        self.assertEqual(
            self.env["mail.test.track.all"]._find_value_from_field_path(
                "one2many_field.monetary_field"
            ),
            "",
        )


class TestSuggestedRecipientsBatchIsBatchV21(BaseHardeningV21):
    """The batch entry point answers exactly as N single-record calls do."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.container = cls.env["mail.test.container"].create({"name": "Container V21"})
        partners = cls.env["res.partner"].create(
            [
                {"name": "A V21", "email": "a.v21@test.example.com"},
                {"name": "B V21", "email": "b.v21@test.example.com"},
            ]
        )
        cls.with_container = cls.env["mail.test.ticket"].create(
            {
                "name": "With container",
                "customer_id": partners[0].id,
                "container_id": cls.container.id,
            }
        )
        cls.without_container = cls.env["mail.test.ticket"].create(
            {"name": "Without container", "customer_id": partners[1].id}
        )
        # 'mail.test.ticket._creation_subtype' answers with this subtype only for a
        # record that has a container, so the message below is a creation message
        # for the first record and an ordinary reply for the second.
        subtype = cls.env.ref("test_mail.st_mail_test_ticket_container_upd")
        for record, email in (
            (cls.with_container, "reply.with.v21@test.example.com"),
            (cls.without_container, "reply.without.v21@test.example.com"),
        ):
            record.message_post(
                body="reply",
                message_type="email",
                subtype_id=subtype.id,
                email_from=email,
                incoming_email_to=email,
            )

    def test_a_record_does_not_inherit_a_siblings_creation_subtype(self):
        records = self.with_container + self.without_container
        batch = records._message_get_suggested_recipients_batch(reply_discussion=True)
        for record in records:
            single = record._message_get_suggested_recipients(reply_discussion=True)
            self.assertEqual(
                self._mailboxes(batch[record.id]),
                self._mailboxes(single),
                f"{record.name}: a batch must answer as the single-record call does",
            )

    def test_a_per_record_creation_subtype_does_not_raise_on_a_batch(self):
        # account.move reads 'move_type' in its override and hr.applicant calls
        # ensure_one(); sorting the batch's messages as one set resolved the
        # subtype once for every record and raised on both.
        records = self.with_container + self.without_container
        with patch.object(
            type(records),
            "_creation_subtype",
            lambda self: self.ensure_one() or self.env["mail.message.subtype"],
        ):
            records._message_get_suggested_recipients_batch(reply_discussion=True)

    def test_a_batch_does_not_read_partners_one_record_at_a_time(self):
        partners = self.env["res.partner"].create(
            [
                {
                    "name": f"Batch {index}",
                    "email": f"batch.{index}.v21@test.example.com",
                }
                for index in range(10)
            ]
        )
        records = self.env["mail.test.ticket"].create(
            [
                {
                    "name": f"Batch {index}",
                    "customer_id": partners[index].id,
                    "email_from": f"from.{index}.v21@test.example.com",
                }
                for index in range(10)
            ]
        )
        self.env.flush_all()
        self.env.invalidate_all()
        one = self._count_queries(records[:1]._message_get_suggested_recipients_batch)
        self.env.invalidate_all()
        ten = self._count_queries(records._message_get_suggested_recipients_batch)
        self.assertLessEqual(
            ten,
            one + 1,
            "the batch must not pay per record: a recordset union carries no "
            "prefetch set beyond its own ids, so every read has to be given one",
        )


class TestBannedEmailsV21(BaseHardeningV21):
    """A falsy value never enters the banned-address set."""

    def test_a_partner_without_an_email_is_still_suggested(self):
        no_mail = self.env["res.partner"].create({"name": "No Mail V21"})
        record = self.env["mail.test.ticket"].create(
            {"name": "No mail ticket", "customer_id": no_mail.id}
        )
        root = self.env.ref("base.partner_root").sudo()
        for value in (False, "OdooBot", "   "):
            with self.subTest(root_email=value):
                root.email = value
                self.env.invalidate_all()
                self.assertEqual(
                    [
                        entry["name"]
                        for entry in record._message_get_suggested_recipients()
                    ],
                    ["No Mail V21"],
                    "an OdooBot address that does not normalise must not ban "
                    "every partner that has no email either",
                )

    def test_the_root_address_itself_is_still_banned(self):
        root = self.env.ref("base.partner_root").sudo()
        root.email = "odoobot.v21@test.example.com"
        record = self.env["mail.test.ticket"].create(
            {"name": "Root ticket", "email_from": root.email}
        )
        self.env.invalidate_all()
        self.assertNotIn(
            root.email,
            [
                entry["email"]
                for entry in record._message_get_suggested_recipients(no_create=True)
            ],
        )
        self.assertEqual(
            record._message_get_default_recipients()[record.id]["email_to"],
            "",
            "the same address is banned for default recipients",
        )


class TestEmailFieldsAreTypedV21(BaseHardeningV21):
    """An address lives in a text column, never in a field that has only the name."""

    def test_a_field_of_another_type_is_not_an_address(self):
        record = self.env["mail.test.track.all"].create(
            {"name": "Typed V21", "boolean_field": True}
        )
        # The fallback list carries 'x_email_from' / 'x_email' / 'x_email_cc' to
        # pick up custom fields, and 'ir_model._instantiate_attrs' assigns
        # '_primary_email = "x_email"' to every custom mail-blacklist model --
        # while nothing constrains the type a user gives that field.
        self.assertFalse(record._mail_find_email_value(("boolean_field",)))

    def test_a_text_field_is_still_an_address(self):
        record = self.env["mail.test.ticket"].create(
            {"name": "Typed V21", "email_from": "typed.v21@test.example.com"}
        )
        self.assertEqual(
            record._mail_find_email_value(record._mail_default_email_fields),
            "typed.v21@test.example.com",
        )

    def test_default_recipients_survive_a_wrongly_typed_fallback_field(self):
        record = self.env["mail.test.track.all"].create(
            {"name": "Typed V21", "boolean_field": True}
        )
        with patch.object(
            type(record), "_mail_default_email_fields", ("boolean_field", "email_from")
        ):
            # Before: AttributeError("'bool' object has no attribute 'strip'")
            defaults = record._message_get_default_recipients()[record.id]
        self.assertEqual(defaults["email_to"], "")

    def test_a_primary_email_field_of_the_wrong_type_is_refused(self):
        model = self.env["mail.test.track.all"]
        with patch.object(type(model), "_primary_email", "boolean_field"):
            self.assertIsNone(model._mail_get_primary_email_field())
        with patch.object(type(model), "_primary_email", ["not_a_str"]):
            self.assertIsNone(
                model._mail_get_primary_email_field(),
                "a non-string must answer None rather than raise TypeError",
            )
        with patch.object(type(model), "_primary_email", "char_field"):
            self.assertEqual(model._mail_get_primary_email_field(), "char_field")


class TestTimezoneFieldIsTypedV21(BaseHardeningV21):
    def test_a_model_without_a_timezone_field_answers_none(self):
        # 'date_tz' / 'tz' / 'timezone' are looked up by name. Every field of
        # those names in the four repos is a Selection or a Char today, so the
        # type guard has no in-tree trigger -- it is the residue of the same
        # heuristic the email fallback list carried.
        record = self.env["mail.test.track.all"].create({"name": "Tz V21"})
        self.assertIsNone(record._mail_get_timezone())

    def test_a_real_timezone_is_still_returned(self):
        partner = self.env["res.partner"].create(
            {"name": "Tz V21", "tz": "Europe/Brussels"}
        )
        self.assertEqual(partner._mail_get_timezone(), "Europe/Brussels")


class TestTrackingSequenceV21(BaseHardeningV21):
    def test_a_field_without_a_tracking_parameter_sorts_last(self):
        # 'track_sequence' had no declaration in any repo; the fallback that read
        # it was evaluated on every call.
        self.assertEqual(
            self.env["mail.test.track.all"]._mail_track_get_field_sequence("name"), 100
        )

    def test_a_declared_tracking_sequence_is_still_honoured(self):
        model = self.env["mail.test.track.all"]
        self.assertEqual(model._mail_track_get_field_sequence("boolean_field"), 1)
        self.assertEqual(model._mail_track_get_field_sequence("char_field"), 2)


class TestReplyToAuthorPrefetchV21(BaseHardeningV21):
    """The author warm-up in '_notify_get_reply_to_batch' is load-bearing."""

    def test_distinct_authors_cost_what_one_shared_author_costs(self):
        self.env.company.alias_domain_id = self.env["mail.alias.domain"].create(
            {
                "name": "v21.test.example.com",
                "catchall_alias": "catchall-v21",
                "bounce_alias": "bounce-v21",
            }
        )
        authors = self.env["res.partner"].create(
            [{"name": f"Author V21 {index}"} for index in range(20)]
        )
        records = self.env["mail.test.ticket"].create(
            [{"name": f"Reply V21 {index}"} for index in range(20)]
        )
        defaults = dict.fromkeys(records.ids, False)
        self.env.flush_all()

        self.env.invalidate_all()
        shared = self._count_queries(
            lambda: records._notify_get_reply_to_batch(
                defaults=defaults, author_ids=dict.fromkeys(records.ids, authors[0].id)
            )
        )
        self.env.invalidate_all()
        distinct = self._count_queries(
            lambda: records._notify_get_reply_to_batch(
                defaults=defaults,
                author_ids=dict(zip(records.ids, authors.ids, strict=True)),
            )
        )
        self.assertEqual(
            distinct,
            shared,
            "the distinct-author case is the one this method exists for; "
            "dropping the author warm-up costs one browse per record",
        )
