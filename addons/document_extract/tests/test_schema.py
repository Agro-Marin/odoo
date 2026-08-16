"""Declaring a document type, and what "complete" is allowed to mean."""

from odoo.tests.common import BaseCase, tagged

from odoo.addons.document_extract.tools.schema import (
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
        """The case required-fields cannot see: everything present, wrong."""
        schema = get_schema("invoice")

        values = {"subtotal": 100.0, "tax_amount": 16.0, "total": 1116.0}

        self.assertEqual(schema.violations(values), ("invoice_totals",))

    def test_a_rule_is_skipped_rather_than_failed_when_a_field_is_absent(self):
        """An incomplete extraction is `missing`, not a contradiction.

        Reporting it as both would make a field nobody produced look like two
        fields that disagree, and send an escalation after the wrong thing.
        """
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
        """Last-one-wins would hide the disagreement, which is the bug."""
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
    from odoo.addons.document_extract.tools import schema as schema_mod

    schema_mod._SCHEMAS.pop(name, None)
