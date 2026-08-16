"""Which strategy runs, when it stops, and what it stops on.

The central test is `test_a_complete_looking_answer_that_breaks_a_rule_escalates`.
It encodes the finding that reshaped this design: a parser can return a full
set of fields and still not have read the document. Stopping on "a strategy
returned something" was measured accepting a real utility bill that had lost
its subtotal, tax, surcharge and total together.
"""

import contextlib

from odoo.tests.common import BaseCase, tagged

from odoo.addons.document_extract.tools import cascade
from odoo.addons.document_extract.tools.candidates import ExtractionResult
from odoo.addons.document_extract.tools.extractors import (
    FREE,
    GENERATIVE,
    METERED,
    BaseExtractor,
    get_extractors,
    register_extractor,
)
from odoo.addons.document_extract.tools.schema import (
    FieldSpec,
    get_schema,
    register_schema,
    sums_to,
)
from odoo.addons.document_extract.tools.source import DocumentSource

_TEXT_DOC = DocumentSource(b"a bill with words on it", "text/plain")
_IMAGE_DOC = DocumentSource(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32, "image/png")


class _Stub(BaseExtractor):
    def __init__(self, name, values, cost=FREE, needs=("text",), confidence=0.9):
        self.name = name
        self.doc_types = ("cascade_test",)
        self.needs = needs
        self.cost = cost
        self.confidence = confidence
        self._values = values
        self.calls = []

    def extract(self, source, doc_type, wanted, env=None):
        self.calls.append(wanted)
        return dict(self._values) if self._values is not None else None


@contextlib.contextmanager
def _registered(*extractors):
    from odoo.addons.document_extract.tools import extractors as mod

    saved = dict(mod._EXTRACTORS)
    mod._EXTRACTORS.clear()
    try:
        for extractor in extractors:
            register_extractor(extractor)
        yield
    finally:
        mod._EXTRACTORS.clear()
        mod._EXTRACTORS.update(saved)


@tagged("post_install", "-at_install")
class TestCascade(BaseCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from odoo.addons.document_extract.tools import schema as schema_mod

        if "cascade_test" not in schema_mod._SCHEMAS:
            register_schema(
                "cascade_test",
                {
                    "subtotal": FieldSpec("float"),
                    "tax": FieldSpec("float"),
                    "total": FieldSpec("float", required=True),
                    "number": FieldSpec("str", required=True),
                },
                rules=[sums_to("totals", ("subtotal", "tax"), "total")],
            )

    def test_a_free_strategy_that_answers_stops_the_cascade(self):
        free = _Stub("free", {"total": 116.0, "number": "A1"})
        pricey = _Stub("pricey", {"total": 999.0, "number": "Z9"}, cost=GENERATIVE)

        with _registered(free, pricey):
            result = cascade.run(_TEXT_DOC, "cascade_test")

        self.assertTrue(result.satisfied)
        self.assertEqual(result.ran, ["free"])
        self.assertEqual(result["total"].value, 116.0)
        self.assertEqual(pricey.calls, [])

    def test_a_missing_required_field_escalates(self):
        partial = _Stub("partial", {"total": 116.0})
        pricey = _Stub("pricey", {"number": "A1"}, cost=GENERATIVE)

        with _registered(partial, pricey):
            result = cascade.run(_TEXT_DOC, "cascade_test")

        self.assertTrue(result.satisfied)
        self.assertEqual(result.ran, ["partial", "pricey"])
        self.assertEqual(result["total"].source, "partial")
        self.assertEqual(result["number"].source, "pricey")

    def test_only_the_gaps_are_asked_for(self):
        """Escalation is per field: what was read is not paid for twice."""
        partial = _Stub("partial", {"total": 116.0})
        pricey = _Stub("pricey", {"number": "A1"}, cost=GENERATIVE)

        with _registered(partial, pricey):
            cascade.run(_TEXT_DOC, "cascade_test")

        self.assertEqual(pricey.calls, [("number",)])

    def test_a_complete_looking_answer_that_breaks_a_rule_escalates(self):
        """Every required field present, and the numbers still contradict.

        This is the case that "did a strategy return something" cannot see,
        and the reason satisfaction is the schema's business.
        """
        wrong = _Stub(
            "wrong", {"subtotal": 100.0, "tax": 16.0, "total": 999.0, "number": "A1"}
        )
        better = _Stub("better", {"total": 116.0}, cost=METERED, confidence=0.95)

        with _registered(wrong, better):
            result = cascade.run(_TEXT_DOC, "cascade_test")

        self.assertEqual(result.ran, ["wrong", "better"])
        self.assertTrue(result.satisfied)
        self.assertEqual(result["total"].value, 116.0)
        self.assertIn("total", result.disputed)

    def test_the_fields_of_a_broken_rule_are_what_gets_asked(self):
        wrong = _Stub(
            "wrong", {"subtotal": 100.0, "tax": 16.0, "total": 999.0, "number": "A1"}
        )
        better = _Stub("better", {"total": 116.0}, cost=METERED)

        with _registered(wrong, better):
            cascade.run(_TEXT_DOC, "cascade_test")

        self.assertEqual(set(better.calls[0]), {"subtotal", "tax", "total"})

    def test_a_cost_ceiling_keeps_the_expensive_strategy_out(self):
        """What a posting path asks for: structured only, no network."""
        partial = _Stub("partial", {"total": 116.0})
        pricey = _Stub("pricey", {"number": "A1"}, cost=GENERATIVE)

        with _registered(partial, pricey):
            result = cascade.run(_TEXT_DOC, "cascade_test", up_to=FREE)

        self.assertFalse(result.satisfied)
        self.assertEqual(result.missing, ("number",))
        self.assertEqual(pricey.calls, [])

    def test_an_incomplete_result_is_returned_not_raised(self):
        with _registered(_Stub("partial", {"total": 1.0})):
            result = cascade.run(_TEXT_DOC, "cascade_test")

        self.assertFalse(result.satisfied)
        self.assertEqual(result.flat(), {"total": 1.0})
        self.assertEqual(result.missing, ("number",))

    def test_a_strategy_that_cannot_read_this_document_never_runs(self):
        needs_image = _Stub("vision", {"total": 1.0}, needs=("images",))

        with _registered(needs_image):
            cascade.run(_TEXT_DOC, "cascade_test")

        self.assertEqual(needs_image.calls, [])

    def test_the_same_strategy_runs_when_the_document_can_feed_it(self):
        needs_image = _Stub(
            "vision", {"total": 116.0, "number": "A1"}, needs=("images",)
        )

        with _registered(needs_image):
            result = cascade.run(_IMAGE_DOC, "cascade_test")

        self.assertTrue(result.satisfied)

    def test_a_failing_strategy_does_not_take_the_document_with_it(self):
        class _Boom(_Stub):
            def extract(self, source, doc_type, wanted, env=None):
                raise RuntimeError("vendor down")

        with _registered(
            _Boom("boom", None),
            _Stub("after", {"total": 116.0, "number": "A1"}, cost=METERED),
        ):
            result = cascade.run(_TEXT_DOC, "cascade_test")

        self.assertTrue(result.satisfied)
        self.assertEqual(result.ran, ["boom", "after"])

    def test_a_strategy_returning_nothing_is_not_an_error(self):
        with _registered(
            _Stub("silent", None),
            _Stub("speaks", {"total": 116.0, "number": "A1"}, cost=METERED),
        ):
            result = cascade.run(_TEXT_DOC, "cascade_test")

        self.assertTrue(result.satisfied)

    def test_a_value_of_the_wrong_type_is_not_recorded(self):
        with _registered(_Stub("sloppy", {"total": "one hundred", "number": "A1"})):
            result = cascade.run(_TEXT_DOC, "cascade_test")

        self.assertNotIn("total", result)
        self.assertEqual(result.missing, ("total",))

    def test_a_field_the_schema_does_not_know_is_kept(self):
        """A strategy reading more than the schema declares is a reason to
        extend the schema, and dropping it silently is how that never
        happens."""
        with _registered(
            _Stub("rich", {"total": 116.0, "number": "A1", "vendor_note": "x"})
        ):
            result = cascade.run(_TEXT_DOC, "cascade_test")

        self.assertEqual(result["vendor_note"].value, "x")

    def test_ordering_is_by_cost_then_confidence(self):
        with _registered(
            _Stub("b_free_low", {}, cost=FREE, confidence=0.2),
            _Stub("a_free_high", {}, cost=FREE, confidence=0.9),
            _Stub("c_metered", {}, cost=METERED, confidence=1.0),
        ):
            names = [e.name for e in get_extractors(_TEXT_DOC, "cascade_test")]

        self.assertEqual(names, ["a_free_high", "b_free_low", "c_metered"])

    def test_an_extractor_needing_an_unknown_representation_is_refused(self):
        bad = _Stub("bad", {}, needs=("pixels",))

        with self.assertRaises(ValueError):
            with _registered(bad):
                pass


@tagged("post_install", "-at_install")
class TestUnhashableValues(BaseCase):
    """A schema field may be a list or a dict, and comparing is not hashing.

    `disputed` built a set of candidate values, which raises rather than
    answering for an invoice's lines or a bill's meter registers. It surfaced
    only when a result was serialised onto a record, so every cascade test
    passed while the mixin could not store what the cascade produced.
    """

    def test_a_list_valued_field_can_be_compared(self):
        result = ExtractionResult(get_schema("invoice"))
        result.add("lines", [{"a": 1}], "one", 0.9)

        self.assertFalse(result["lines"].disputed)

    def test_two_readers_disagreeing_about_a_list_is_a_dispute(self):
        result = ExtractionResult(get_schema("invoice"))
        result.add("lines", [{"a": 1}], "one", 0.9)
        result.add("lines", [{"a": 2}], "other", 0.5)

        self.assertTrue(result["lines"].disputed)
        self.assertEqual(result["lines"].value, [{"a": 1}])

    def test_two_readers_agreeing_about_a_list_is_not(self):
        result = ExtractionResult(get_schema("invoice"))
        result.add("lines", [{"a": 1}], "one", 0.9)
        result.add("lines", [{"a": 1}], "other", 0.5)

        self.assertFalse(result["lines"].disputed)
