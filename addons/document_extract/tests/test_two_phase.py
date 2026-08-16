"""A strategy that answers later, and the machinery that lets it.

Some services accept a document and prepare an answer over seconds or minutes.
That cannot be a function returning a value, so such a strategy submits and is
polled, and the cascade reaches it only when the caller can wait.

Tested with a service that answers on the third ask, because the interesting
behaviour is entirely in the waiting: that a synchronous caller never starts
one, that a waiting result is not mistaken for a failed one, and above all that
asking again asks about the *same submission* rather than sending the document
a second time -- which is what would turn a metered service into a bill.
"""

import contextlib
from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged

from odoo.addons.document_extract.tools import (
    FREE,
    METERED,
    PENDING,
    BaseExtractor,
    cascade,
)
from odoo.addons.document_extract.tools import extractors as registry
from odoo.addons.document_extract.tools.schema import FieldSpec, register_schema
from odoo.addons.document_extract.tools.source import DocumentSource

_DOC = DocumentSource(b"a document with words", "text/plain", "doc.txt")


class _Slow(BaseExtractor):
    """A service that accepts a document and answers on the Nth ask."""

    name = "slow_service"
    doc_types = ("two_phase_test",)
    needs = ("text",)
    cost = METERED
    confidence = 0.8

    def __init__(self, answer_on=3, values=None):
        self.answer_on = answer_on
        self.values = values if values is not None else {"total": 42.0}
        self.submissions = []
        self.polls = []

    def submit(self, source, doc_type, wanted, env=None):
        handle = f"token-{len(self.submissions)}"
        self.submissions.append(handle)
        return handle

    def poll(self, handle, env=None):
        self.polls.append(handle)
        if len(self.polls) < self.answer_on:
            return PENDING
        return dict(self.values)


class _Quick(BaseExtractor):
    name = "quick"
    doc_types = ("two_phase_test",)
    needs = ("text",)
    cost = FREE
    confidence = 0.9

    def __init__(self, values):
        self.values = values

    def extract(self, source, doc_type, wanted, env=None):
        return dict(self.values) if self.values else None


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


@tagged("post_install", "-at_install")
class TestTwoPhase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from odoo.addons.document_extract.tools import schema as schema_mod

        if "two_phase_test" not in schema_mod._SCHEMAS:
            register_schema(
                "two_phase_test",
                {
                    "total": FieldSpec("float", required=True),
                    "note": FieldSpec("str"),
                },
            )

    # -- the cascade --------------------------------------------------

    def test_a_caller_that_cannot_wait_never_starts_a_slow_service(self):
        """A posting path must not hand a document to something that answers
        in minutes, however cheap it is."""
        slow = _Slow()

        with _only(slow):
            result = cascade.run(_DOC, "two_phase_test")

        self.assertEqual(slow.submissions, [])
        self.assertFalse(result.waiting)
        self.assertEqual(result.missing, ("total",))

    def test_a_caller_that_can_wait_submits_and_says_it_is_waiting(self):
        slow = _Slow()

        with _only(slow):
            result = cascade.run(_DOC, "two_phase_test", allow_pending=True)

        self.assertTrue(result.waiting)
        self.assertEqual(result.pending["strategy"], "slow_service")
        self.assertEqual(result.pending["handle"], "token-0")
        self.assertEqual(slow.submissions, ["token-0"])

    def test_asking_again_asks_about_the_same_submission(self):
        """The property that keeps a metered service from being paid twice.

        Note the shape of the run: the first call submits and does not poll, so
        a service answering on its third poll is reached on the fourth call.
        """
        slow = _Slow(answer_on=3)

        with _only(slow):
            result = cascade.run(_DOC, "two_phase_test", allow_pending=True)
            waited = []
            for _ in range(3):
                result = cascade.run(
                    _DOC,
                    "two_phase_test",
                    allow_pending=True,
                    pending=result.pending,
                )
                waited.append(result.waiting)

        self.assertEqual(slow.submissions, ["token-0"])
        self.assertEqual(slow.polls, ["token-0"] * 3)
        self.assertEqual(waited, [True, True, False])
        self.assertEqual(result["total"].value, 42.0)
        self.assertTrue(result.satisfied)

    def test_a_cheap_strategy_that_answers_means_the_service_is_never_asked(self):
        slow = _Slow()

        with _only(_Quick({"total": 1.0}), slow):
            result = cascade.run(_DOC, "two_phase_test", allow_pending=True)

        self.assertTrue(result.satisfied)
        self.assertEqual(slow.submissions, [])

    def test_a_service_that_declines_the_document_is_not_waited_on(self):
        class _Declines(_Slow):
            def submit(self, source, doc_type, wanted, env=None):
                return None

        with _only(_Declines()):
            result = cascade.run(_DOC, "two_phase_test", allow_pending=True)

        self.assertFalse(result.waiting)
        self.assertIn("slow_service", result.ran)

    def test_a_service_that_breaks_on_submission_does_not_take_the_run_with_it(self):
        class _Breaks(_Slow):
            def submit(self, source, doc_type, wanted, env=None):
                raise RuntimeError("service down")

        with _only(_Breaks()):
            result = cascade.run(_DOC, "two_phase_test", allow_pending=True)

        self.assertFalse(result.waiting)
        self.assertEqual(result.missing, ("total",))

    def test_a_service_that_breaks_while_being_asked_again_does_not_either(self):
        class _BreaksLater(_Slow):
            def poll(self, handle, env=None):
                raise RuntimeError("service down")

        with _only(_BreaksLater()):
            result = cascade.run(
                _DOC,
                "two_phase_test",
                allow_pending=True,
                pending={"strategy": "slow_service", "handle": "token-0"},
            )

        self.assertFalse(result.waiting)

    def test_waiting_on_a_strategy_that_no_longer_exists_starts_over(self):
        """A module uninstalled between two attempts must not strand a document."""
        with _only(_Quick({"total": 7.0})):
            result = cascade.run(
                _DOC,
                "two_phase_test",
                allow_pending=True,
                pending={"strategy": "gone", "handle": "token-0"},
            )

        self.assertFalse(result.waiting)
        self.assertEqual(result["total"].value, 7.0)

    # -- the record ----------------------------------------------------

    def _attachment(self):
        return self.env["ir.attachment"].create(
            {
                "name": "slow.txt",
                "raw": b"a document with words",
                "mimetype": "text/plain",
                "extract_document_type": "two_phase_test",
            }
        )

    def test_a_reading_that_can_wait_records_what_it_waits_on(self):
        slow = _Slow()

        with _only(slow):
            attachment = self._attachment()
            attachment._extract_document(allow_pending=True)

        self.assertEqual(attachment.extract_state, "waiting")
        self.assertEqual(attachment.extract_pending["handle"], "token-0")

    def test_the_next_attempt_resumes_rather_than_resubmitting(self):
        slow = _Slow(answer_on=1)

        with _only(slow):
            attachment = self._attachment()
            attachment._extract_document(allow_pending=True)
            attachment._extract_document(allow_pending=True)

        self.assertEqual(slow.submissions, ["token-0"])
        self.assertEqual(attachment.extract_state, "done")
        self.assertEqual(attachment.extract_result["total"]["value"], 42.0)
        self.assertFalse(attachment.extract_pending)

    def test_the_job_asks_the_queue_to_come_back_rather_than_failing(self):
        """Waiting is not an error, and must not spend the retry budget.

        `_defer` refuses to be called outside a running job, which is why this
        asserts on the call rather than running `_job_extract` bare: a job
        entry point invoked by hand is not a job.
        """
        slow = _Slow()

        with _only(slow), patch.object(type(self.env["ir.job"]), "_defer") as defer:
            attachment = self._attachment()
            attachment._job_extract()

        defer.assert_called_once()
        self.assertIn("slow_service", defer.call_args.kwargs["reason"])
        self.assertEqual(attachment.extract_state, "waiting")

    def test_a_synchronous_reading_of_the_same_record_does_not_submit(self):
        slow = _Slow()

        with _only(slow):
            attachment = self._attachment()
            attachment.action_extract()

        self.assertEqual(slow.submissions, [])
        self.assertEqual(attachment.extract_state, "partial")
