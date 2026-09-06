import datetime

from odoo.tests.common import BaseCase, tagged

from odoo.addons.extract.tools.candidates import ExtractionResult
from odoo.addons.extract.tools.schema import (
    FieldSpec,
    Rule,
    Schema,
    extend_schema,
    get_schema,
    known_schemas,
    not_after,
    register_schema,
    sums_to,
)


@tagged("post_install", "-at_install")
class TestSchema(BaseCase):
    def test_the_shipped_types_are_registered(self):
        for name in ("invoice", "receipt", "utility_bill", "generic"):
            with self.subTest(name=name):
                self.assertIn(name, known_schemas())

    def test_an_unknown_type_names_the_ones_that_exist(self):
        with self.assertRaises(ValueError) as caught:
            get_schema("nope")

        self.assertIn("invoice", str(caught.exception))

    def test_required_fields_are_what_is_missing(self):
        schema = get_schema("invoice")

        self.assertEqual(
            schema.missing({"total": 10.0}),
            ("invoice_date",),
        )
        self.assertEqual(
            schema.missing({"total": 10.0, "invoice_date": "2026-01-01"}), ()
        )

    def test_a_rule_holds_when_the_numbers_agree(self):
        schema = get_schema("invoice")

        values = {"subtotal": 100.0, "tax_amount": 16.0, "total": 116.0}

        self.assertEqual(schema.violations(values), ())

    def test_a_rule_fails_when_they_do_not(self):
        schema = get_schema("invoice")

        values = {"subtotal": 100.0, "tax_amount": 16.0, "total": 1116.0}

        self.assertEqual(schema.violations(values), ("invoice_totals",))

    def test_a_rule_is_skipped_rather_than_failed_when_a_field_is_absent(self):
        schema = get_schema("invoice")

        self.assertEqual(schema.violations({"subtotal": 100.0, "total": 116.0}), ())

    def test_dates_out_of_order_are_a_violation(self):
        schema = get_schema("invoice")

        values = {"invoice_date": "2026-05-01", "due_date": "2026-01-01"}

        self.assertEqual(schema.violations(values), ("invoice_dates",))

    def test_a_field_spec_checks_the_type_it_declares(self):
        self.assertTrue(FieldSpec("float").accepts(1))
        self.assertTrue(FieldSpec("float").accepts(1.5))
        self.assertFalse(FieldSpec("float").accepts("1.5"))
        self.assertTrue(FieldSpec("str").accepts(None))

    def test_a_field_spec_coerces_what_a_document_actually_prints(self):
        self.assertEqual(FieldSpec("float").coerce("$1,234.56"), 1234.56)
        self.assertEqual(FieldSpec("float").coerce("(421.35)"), -421.35)
        self.assertEqual(FieldSpec("float").coerce("1.234,56 €"), 1234.56)
        self.assertEqual(FieldSpec("int").coerce("1.200,00"), 1200)

    def test_a_date_coerces_to_its_iso_string(self):
        self.assertEqual(FieldSpec("date").coerce("2026-03-12"), "2026-03-12")
        self.assertEqual(
            FieldSpec("date").coerce(datetime.date(2026, 3, 12)), "2026-03-12"
        )

    def test_what_states_nothing_of_the_kind_still_raises(self):
        for spec, value in (
            (FieldSpec("float"), True),
            (FieldSpec("float"), "see attached"),
            (FieldSpec("int"), "3.5"),
            (FieldSpec("date"), "last Tuesday"),
            (FieldSpec("date"), "12/03/2026"),
        ):
            with self.subTest(type=spec.type, value=value):
                with self.assertRaises(ValueError):
                    spec.coerce(value)

    def test_a_list_that_declares_no_rows_says_nothing_about_them(self):
        # The state every shipped list was in: `isinstance(value, list)` is the
        # whole contract, so a row of any shape passes and every consumer has to
        # guess the keys separately.
        spec = FieldSpec("list")

        self.assertIsNone(spec.items)
        self.assertTrue(spec.accepts([{"anything": "at all"}]))
        self.assertEqual(
            spec.coerce([{"anything": "at all"}]), [{"anything": "at all"}]
        )

    def test_a_declared_row_is_coerced_the_way_a_field_is(self):
        spec = FieldSpec(
            "list",
            items={
                "date": FieldSpec("date"),
                "description": FieldSpec("str", required=True),
                "amount": FieldSpec("float", required=True),
            },
        )

        rows = spec.coerce(
            [{"date": "2026-03-12", "description": "Deposit", "amount": "1.234,56"}]
        )

        self.assertEqual(
            rows,
            [{"date": "2026-03-12", "description": "Deposit", "amount": 1234.56}],
        )

    def test_a_row_inherits_the_refusal_to_guess_an_ambiguous_date(self):
        # `to_date` will not read a bare 12/03/2026, because it is March in one
        # country and December in another. A row does not get to guess either:
        # the key is dropped and the rest of the row survives.
        spec = FieldSpec(
            "list",
            items={
                "date": FieldSpec("date"),
                "description": FieldSpec("str", required=True),
            },
        )

        rows = spec.coerce([{"date": "12/03/2026", "description": "Deposit"}])

        self.assertEqual(rows, [{"description": "Deposit"}])

    def test_a_row_missing_a_required_key_is_dropped_and_the_rest_kept(self):
        # One unreadable row must not discard the list. Raising would send the
        # cascade back to a more expensive strategy for a list it had read.
        spec = FieldSpec(
            "list",
            items={
                "description": FieldSpec("str", required=True),
                "amount": FieldSpec("float", required=True),
            },
        )

        rows = spec.coerce(
            [
                {"description": "Kept", "amount": 10.0},
                {"description": "No amount"},
                {"amount": 20.0},
                "not a row at all",
                {"description": "Also kept", "amount": "30"},
            ]
        )

        self.assertEqual(
            rows,
            [
                {"description": "Kept", "amount": 10.0},
                {"description": "Also kept", "amount": 30.0},
            ],
        )

    def test_a_key_the_row_does_not_declare_still_survives(self):
        spec = FieldSpec("list", items={"amount": FieldSpec("float", required=True)})

        rows = spec.coerce([{"amount": "5", "bank_reference": "XYZ-1"}])

        self.assertEqual(rows, [{"bank_reference": "XYZ-1", "amount": 5.0}])

    def test_an_unreadable_value_drops_its_key_rather_than_its_row(self):
        spec = FieldSpec(
            "list",
            items={
                "description": FieldSpec("str", required=True),
                "date": FieldSpec("date"),
            },
        )

        rows = spec.coerce([{"description": "Kept", "date": "the third of never"}])

        self.assertEqual(rows, [{"description": "Kept"}])

    def test_a_list_whose_every_row_was_unreadable_reads_as_nothing(self):
        # Not []. `Schema.missing` asks `is None`, so an empty list satisfies a
        # requirement while carrying nothing -- a statement whose every
        # transaction was a misread would report itself fully read.
        spec = FieldSpec("list", items={"amount": FieldSpec("float", required=True)})

        self.assertIsNone(spec.coerce([{"amount": "not a number"}, "not a row"]))

    def test_a_required_list_of_unreadable_rows_reports_itself_missing(self):
        # End to end, because this is the chain that matters: a strategy hands
        # `add` a list of rows, every one of them is unreadable, and the result
        # must say the field was not read rather than that it was read empty.
        schema = Schema(
            name="test_rows_required",
            fields={
                "rows": FieldSpec(
                    "list",
                    required=True,
                    items={"amount": FieldSpec("float", required=True)},
                )
            },
        )
        result = ExtractionResult(schema)

        result.add("rows", [{"amount": "not a number"}, "not a row"], "stub", 0.9)

        self.assertEqual(result.flat().get("rows"), None)
        self.assertEqual(result.missing, ("rows",))
        self.assertFalse(result.satisfied)

    def test_a_bare_value_becomes_the_one_key_a_row_requires(self):
        # A CV's skills are "Python" as readily as {"name": "Python"}, and the
        # prompt invited the bare form for as long as a list showed as ["..."].
        spec = FieldSpec(
            "list",
            items={"name": FieldSpec("str", required=True), "level": FieldSpec("str")},
        )

        self.assertEqual(
            spec.coerce(["Python", {"name": "SQL", "level": "expert"}]),
            [{"name": "Python"}, {"name": "SQL", "level": "expert"}],
        )

    def test_a_bare_value_is_dropped_when_a_row_requires_two_keys(self):
        # There is no place to put it, and choosing one would be exactly the
        # unwritten contract this declaration exists to end.
        spec = FieldSpec(
            "list",
            items={
                "description": FieldSpec("str", required=True),
                "amount": FieldSpec("float", required=True),
            },
        )

        self.assertIsNone(spec.coerce(["a transaction, apparently"]))

    def test_a_bare_value_is_dropped_when_a_row_requires_none(self):
        spec = FieldSpec("list", items={"note": FieldSpec("str")})

        self.assertIsNone(spec.coerce(["loose text"]))

    def test_only_a_list_declares_rows(self):
        with self.assertRaises(ValueError):
            FieldSpec("str", items={"name": FieldSpec("str")})

    def test_a_row_is_one_level_deep(self):
        with self.assertRaises(ValueError):
            FieldSpec(
                "list",
                items={"nested": FieldSpec("list", items={"x": FieldSpec("str")})},
            )

    def test_every_shipped_list_declares_its_rows(self):
        # The gap this closes: six list fields across five schemas, none of which
        # said what a row looked like, while two consumers read two different
        # undeclared sets of keys.
        for name in known_schemas():
            schema = get_schema(name)
            for field_name, spec in schema.fields.items():
                if spec.type != "list":
                    continue
                with self.subTest(schema=name, field=field_name):
                    self.assertIsNotNone(
                        spec.items,
                        f"{name}.{field_name} is a list that says nothing about "
                        "its rows",
                    )

    def test_an_unknown_field_type_is_refused_at_declaration(self):
        with self.assertRaises(ValueError):
            FieldSpec("monetary")

    def test_a_type_cannot_be_registered_twice(self):
        register_schema("test_dup", {"a": FieldSpec("str")})
        try:
            with self.assertRaises(ValueError):
                register_schema("test_dup", {"a": FieldSpec("str")})
        finally:
            _forget("test_dup")

    def test_a_localization_extends_without_forking(self):
        register_schema("test_ext", {"total": FieldSpec("float", required=True)})
        try:
            extend_schema("test_ext", {"uuid": FieldSpec("str", required=True)})
            schema = get_schema("test_ext")

            self.assertEqual(sorted(schema.required), ["total", "uuid"])
        finally:
            _forget("test_ext")

    def test_two_modules_cannot_disagree_about_one_field(self):
        register_schema("test_clash", {"total": FieldSpec("float")})
        try:
            with self.assertRaises(ValueError):
                extend_schema("test_clash", {"total": FieldSpec("str")})
        finally:
            _forget("test_clash")

    def test_a_custom_rule_reads_the_flat_values(self):
        schema = Schema(
            name="x",
            fields={"a": FieldSpec("float"), "b": FieldSpec("float")},
            rules=(Rule("a_below_b", ("a", "b"), lambda v: v["a"] < v["b"]),),
        )

        self.assertEqual(schema.violations({"a": 1.0, "b": 2.0}), ())
        self.assertEqual(schema.violations({"a": 3.0, "b": 2.0}), ("a_below_b",))

    def test_the_rule_helpers_build_what_they_say(self):
        rule = sums_to("t", ("a", "b"), "c")
        self.assertTrue(rule.holds({"a": 1.0, "b": 2.0, "c": 3.0}))
        self.assertFalse(rule.holds({"a": 1.0, "b": 2.0, "c": 9.0}))

        ordering = not_after("d", "start", "end")
        self.assertTrue(ordering.holds({"start": "2026-01-01", "end": "2026-02-01"}))
        self.assertFalse(ordering.holds({"start": "2026-03-01", "end": "2026-02-01"}))


def _forget(name):
    from odoo.addons.extract.tools import schema as schema_mod

    schema_mod._SCHEMAS.pop(name, None)
