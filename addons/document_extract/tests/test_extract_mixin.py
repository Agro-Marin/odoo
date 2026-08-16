"""What a record gets by inheriting the mixin, tested on an attachment.

``ir.attachment`` is the framework's own consumer and the right subject for
these: a record whose entire content is the document, with no business fields
to fill and nothing to predict. Anything the mixin needs that an attachment
cannot give would mean the mixin is asking for too much.

The queued path is tested by what it enqueues rather than by running a worker.
``ir.job`` has its own suite in ``base`` for the running; what belongs here is
that this module hands it the right job -- on its channel, with an identity key
that makes a second enqueue a no-op.
"""

import contextlib

import pymupdf

from odoo.tests.common import TransactionCase, tagged

from odoo.addons.document_extract.tools import FREE, GENERATIVE, BaseExtractor
from odoo.addons.document_extract.tools import extractors as registry
from odoo.addons.document_extract.tools.schema import FieldSpec, register_schema


class _Stub(BaseExtractor):
    name = "mixin_test_stub"
    doc_types = ("mixin_test",)
    needs = ("text",)
    cost = FREE
    confidence = 0.9

    def __init__(self, values):
        self._values = values
        self.calls = 0

    def extract(self, source, doc_type, wanted, env=None):
        self.calls += 1
        return dict(self._values) if self._values else None


@contextlib.contextmanager
def _only(*extractors):
    saved = dict(registry._EXTRACTORS)
    registry._EXTRACTORS.clear()
    try:
        for extractor in extractors:
            registry.register_extractor(extractor)
        yield
    finally:
        registry._EXTRACTORS.clear()
        registry._EXTRACTORS.update(saved)


def _pdf(text="TOTAL 139.86"):
    doc = pymupdf.open()
    page = doc.new_page()
    for i in range(6):
        page.insert_text((40, 60 + i * 16), f"{text} line {i}")
    return doc.tobytes()


@tagged("post_install", "-at_install")
class TestExtractMixin(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from odoo.addons.document_extract.tools import schema as schema_mod

        if "mixin_test" not in schema_mod._SCHEMAS:
            register_schema(
                "mixin_test",
                {
                    "title": FieldSpec("str"),
                    "total": FieldSpec("float", required=True),
                    "reference": FieldSpec("str", required=True),
                },
            )

    def _attachment(self, data=None, doc_type="mixin_test", name="doc.pdf"):
        return self.env["ir.attachment"].create(
            {
                "name": name,
                "raw": _pdf() if data is None else data,
                "mimetype": "application/pdf",
                "extract_document_type": doc_type,
            }
        )

    # -- states -------------------------------------------------------

    def test_a_complete_reading_is_done(self):
        with _only(_Stub({"total": 139.86, "reference": "A1"})):
            attachment = self._attachment()

            attachment.action_extract()

        self.assertEqual(attachment.extract_state, "done")
        self.assertEqual(attachment.extract_missing["fields"], [])

    def test_an_incomplete_reading_is_partial_and_names_what_is_missing(self):
        """The state that exists so nine fields of eleven are not thrown away."""
        with _only(_Stub({"total": 139.86})):
            attachment = self._attachment()

            attachment.action_extract()

        self.assertEqual(attachment.extract_state, "partial")
        self.assertEqual(attachment.extract_missing["fields"], ["reference"])
        self.assertEqual(attachment.extract_result["total"]["value"], 139.86)

    def test_a_document_with_nothing_to_read_fails_without_raising(self):
        with _only(_Stub(None)):
            attachment = self._attachment()

            attachment.action_extract()

        self.assertEqual(attachment.extract_state, "partial")
        self.assertFalse(attachment.extract_result)

    def test_a_record_with_no_document_says_so(self):
        attachment = self.env["ir.attachment"].create(
            {"name": "empty.txt", "extract_document_type": "mixin_test"}
        )

        attachment.action_extract()

        self.assertEqual(attachment.extract_state, "failed")
        self.assertIn("No document", attachment.extract_error)

    def test_a_type_no_module_registers_is_refused_by_name(self):
        attachment = self._attachment()
        attachment.extract_document_type = False

        with self.assertRaises(ValueError):
            attachment.action_extract()

    # -- provenance ---------------------------------------------------

    def test_the_result_keeps_which_strategy_read_each_field(self):
        with _only(_Stub({"total": 139.86, "reference": "A1"})):
            attachment = self._attachment()

            attachment.action_extract()

        self.assertEqual(
            attachment.extract_result["total"]["source"], "mixin_test_stub"
        )
        self.assertEqual(attachment.extract_result["total"]["confidence"], 0.9)

    def test_a_disagreement_between_strategies_is_kept_not_resolved_away(self):
        """Both answers survive; the more confident one is the value.

        The cheap strategy has to leave the schema unsatisfied for the second
        one to run at all -- which is the cascade working, and the reason this
        test reads the way it does rather than by giving both strategies a
        complete answer.
        """
        cheap = _Stub({"total": 100.0})
        careful = _Stub({"total": 139.86, "reference": "A1"})
        careful.name = "careful"
        careful.cost = GENERATIVE
        careful.confidence = 0.95

        with _only(cheap, careful):
            attachment = self._attachment()

            attachment.action_extract()

        total = attachment.extract_result["total"]
        self.assertTrue(total["disputed"])
        self.assertEqual(len(total["candidates"]), 2)
        self.assertEqual(total["value"], 139.86)
        self.assertEqual(total["source"], "careful")
        self.assertEqual(attachment.extract_state, "done")

    # -- corrections --------------------------------------------------

    def test_a_person_disagreeing_with_the_reader_is_recorded(self):
        """The labelled example other extraction systems throw away."""
        with _only(_Stub({"total": 139.86, "reference": "A1", "title": "Bill"})):
            attachment = self._attachment()
            attachment.action_extract()

            with self._targeting({"title": "name"}):
                attachment.write({"name": "The real name"})

        correction = attachment.extract_corrections["title"]
        self.assertEqual(correction["read"], "Bill")
        self.assertEqual(correction["read_by"], "mixin_test_stub")
        self.assertEqual(correction["corrected_to"], "The real name")

    def test_agreeing_with_the_reader_is_not_a_correction(self):
        with _only(_Stub({"total": 1.0, "reference": "A1", "title": "Bill"})):
            attachment = self._attachment()
            attachment.action_extract()

            with self._targeting({"title": "name"}):
                attachment.write({"name": "Bill"})

        self.assertFalse(attachment.extract_corrections)

    def test_nothing_is_recorded_before_an_extraction(self):
        with self._targeting({"title": "name"}):
            attachment = self._attachment()
            attachment.write({"name": "renamed before reading"})

        self.assertFalse(attachment.extract_corrections)

    @contextlib.contextmanager
    def _targeting(self, mapping):
        """Give ir.attachment a field mapping for the length of a test."""
        model = self.env["ir.attachment"]
        saved = type(model)._extract_target
        type(model)._extract_target = mapping
        try:
            yield
        finally:
            type(model)._extract_target = saved

    # -- the queue ----------------------------------------------------

    def test_queueing_produces_a_pending_job_on_our_channel(self):
        attachment = self._attachment()

        job = attachment._extract_later()

        self.assertEqual(job.state, "pending")
        self.assertEqual(job.channel, "document_extract")
        self.assertEqual(job.method_name, "_job_extract")
        self.assertEqual(job.model_name, "ir.attachment")
        self.assertEqual(attachment.extract_state, "queued")

    def test_queueing_twice_does_not_produce_two_jobs(self):
        """A sweep that runs hourly must not collect a second job per document."""
        attachment = self._attachment()

        first = attachment._extract_later()
        second = attachment._extract_later()

        self.assertEqual(first, second)

    def test_two_documents_get_their_own_jobs(self):
        one = self._attachment(name="one.pdf")
        other = self._attachment(name="two.pdf")

        self.assertNotEqual(one._extract_later(), other._extract_later())

    def test_the_queued_reading_is_the_same_reading(self):
        with _only(_Stub({"total": 139.86, "reference": "A1"})):
            attachment = self._attachment()

            attachment._job_extract()

        self.assertEqual(attachment.extract_state, "done")

    def test_a_delay_becomes_the_job_clock(self):
        attachment = self._attachment()

        job = attachment._extract_later(delay=600)

        self.assertTrue(job.eta)
