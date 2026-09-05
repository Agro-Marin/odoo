import json

from odoo.tests.common import BaseCase, tagged

from odoo.addons.document_extract.tools.schema import (
    FieldSpec,
    Schema,
    sums_to,
)
from odoo.addons.document_extract_ai.models.prompt import prepare_prompt

_SCHEMA = Schema(
    name="test_bill",
    fields={
        "vendor": FieldSpec("str", help="Who issued it"),
        "issued_on": FieldSpec("date", required=True),
        "subtotal": FieldSpec("float"),
        "tax": FieldSpec("float"),
        "total": FieldSpec("float", required=True),
        "lines": FieldSpec(
            "list",
            items={
                "description": FieldSpec("str", required=True),
                "quantity": FieldSpec("float"),
                "unit_price": FieldSpec("float"),
            },
        ),
    },
    rules=(sums_to("totals", ("subtotal", "tax"), "total"),),
)


@tagged("post_install", "-at_install")
class TestPrompt(BaseCase):
    def test_it_asks_for_every_declared_field(self):
        prompt = prepare_prompt(_SCHEMA)

        for name in _SCHEMA.fields:
            self.assertIn(name, prompt)

    def test_the_shape_it_shows_is_valid_json(self):
        prompt = prepare_prompt(_SCHEMA)
        block = prompt.split("Expected JSON structure:\n", 1)[1].split("\n\nRules:", 1)[
            0
        ]

        shape = json.loads(block)

        self.assertEqual(set(shape), set(_SCHEMA.fields))

    def test_a_type_becomes_an_instruction_about_format(self):
        prompt = prepare_prompt(_SCHEMA)

        self.assertIn("YYYY-MM-DD", prompt)

    def test_required_fields_are_named_as_required(self):
        prompt = prepare_prompt(_SCHEMA)

        self.assertIn("issued_on", prompt)
        self.assertRegex(prompt, r"issued_on:.*required")

    def test_help_text_reaches_the_model(self):
        self.assertIn("Who issued it", prepare_prompt(_SCHEMA))

    def test_the_rules_the_answer_will_be_checked_against_are_stated(self):
        prompt = prepare_prompt(_SCHEMA)

        self.assertIn("subtotal + tax should equal total", prompt)

    def test_it_forbids_invention(self):
        prompt = prepare_prompt(_SCHEMA)

        self.assertIn("Never invent a value", prompt)
        self.assertIn("null", prompt)

    def test_a_list_shows_the_row_it_wants_rather_than_an_ellipsis(self):
        # Until a list could declare its rows, every one of them reached the
        # model as ["..."] -- an array of something -- and a model that answered
        # {"desc": ..., "qty": ...} satisfied the prompt exactly while the
        # consumer read description/quantity and silently produced empty lines.
        prompt = prepare_prompt(_SCHEMA)
        block = prompt.split("Expected JSON structure:\n", 1)[1].split("\n\nRules:", 1)[
            0
        ]

        shape = json.loads(block)

        self.assertEqual(len(shape["lines"]), 1)
        self.assertEqual(
            set(shape["lines"][0]), {"description", "quantity", "unit_price"}
        )
        self.assertNotIn("...", shape["lines"][0].values())

    def test_a_row_says_which_of_its_keys_it_cannot_do_without(self):
        prompt = prepare_prompt(_SCHEMA)

        self.assertIn("a row without description is not a row", prompt)

    def test_asking_for_two_fields_asks_about_two_fields(self):
        prompt = prepare_prompt(_SCHEMA, wanted=("total", "issued_on"))
        block = prompt.split("Expected JSON structure:\n", 1)[1].split("\n\nRules:", 1)[
            0
        ]

        self.assertEqual(set(json.loads(block)), {"total", "issued_on"})
        self.assertNotIn('"vendor"', prompt)

    def test_a_narrowed_prompt_keeps_only_the_rules_that_still_apply(self):
        prompt = prepare_prompt(_SCHEMA, wanted=("vendor",))

        self.assertNotIn("should equal total", prompt)

    def test_a_field_the_schema_does_not_have_is_ignored_not_echoed(self):
        prompt = prepare_prompt(_SCHEMA, wanted=("total", "made_up_field"))

        self.assertNotIn("made_up_field", prompt)

    def test_an_entirely_unknown_request_falls_back_to_the_whole_schema(self):
        prompt = prepare_prompt(_SCHEMA, wanted=("nonsense",))
        block = prompt.split("Expected JSON structure:\n", 1)[1].split("\n\nRules:", 1)[
            0
        ]

        self.assertEqual(set(json.loads(block)), set(_SCHEMA.fields))

    def test_every_shipped_schema_produces_a_prompt(self):
        from odoo.addons.document_extract.tools.schema import get_schema, known_schemas

        for name in known_schemas():
            with self.subTest(schema=name):
                prompt = prepare_prompt(get_schema(name))

                self.assertIn(name.replace("_", " "), prompt)
                block = prompt.split("Expected JSON structure:\n", 1)[1]
                json.loads(block.split("\n\nRules:", 1)[0])
