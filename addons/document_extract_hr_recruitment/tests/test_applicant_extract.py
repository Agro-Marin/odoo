import contextlib

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.document_extract.tools import FREE, BaseExtractor
from odoo.addons.document_extract.tools import extractors as registry


class _Stub(BaseExtractor):
    name = "cv_test_stub"
    doc_types = ("resume",)
    needs = ("text",)
    cost = FREE
    confidence = 0.9

    def __init__(self, values):
        self._values = values

    def extract(self, source, doc_type, wanted, env=None):
        return dict(self._values) if self._values else None


@contextlib.contextmanager
def _only(extractor):
    saved = dict(registry._EXTRACTORS)
    registry._EXTRACTORS.clear()
    try:
        registry.register_extractor(extractor)
        yield
    finally:
        registry._EXTRACTORS.clear()
        registry._EXTRACTORS.update(saved)


_READ = {
    "full_name": "Ada Lovelace",
    "email": "ada@example.com",
    "phone": "+52 55 1234 5678",
}


@tagged("post_install", "-at_install")
class TestApplicantExtraction(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.job = cls.env["hr.job"].create({"name": "Analyst"})

    def _applicant(self, **values):
        applicant = self.env["hr.applicant"].create({"job_id": self.job.id, **values})
        self.env["ir.attachment"].create(
            {
                "name": "cv.txt",
                "res_model": "hr.applicant",
                "res_id": applicant.id,
                "mimetype": "text/plain",
                "raw": b"a curriculum vitae with words on it",
            }
        )
        return applicant

    def test_it_fills_the_header_from_the_cv(self):
        with _only(_Stub(_READ)):
            applicant = self._applicant()

            applicant.action_extract_document()

        self.assertEqual(applicant.partner_name, "Ada Lovelace")
        self.assertEqual(applicant.email_from, "ada@example.com")
        self.assertEqual(applicant.partner_phone, "+52 55 1234 5678")
        self.assertEqual(applicant.extract_state, "done")

    def test_it_does_not_overwrite_what_a_recruiter_typed(self):
        """The replaced module preferred the reading; this one prefers the person."""
        with _only(_Stub(_READ)):
            applicant = self._applicant(partner_name="the name I was told")

            applicant.action_extract_document()

        self.assertEqual(applicant.partner_name, "the name I was told")
        self.assertEqual(applicant.email_from, "ada@example.com")

    def test_it_keeps_which_reader_produced_each_value(self):
        with _only(_Stub(_READ)):
            applicant = self._applicant()

            applicant.action_extract_document()

        self.assertEqual(
            applicant.extract_result["full_name"]["source"], "cv_test_stub"
        )

    def test_a_new_applicant_can_be_read(self):
        applicant = self._applicant()

        self.assertTrue(applicant.extract_can_be_read)

    def test_an_applicant_past_the_first_stage_is_not_read(self):
        applicant = self._applicant()
        later = self.env["hr.recruitment.stage"].search(
            [("fold", "=", False)], order="sequence desc", limit=1
        )
        applicant.stage_id = later

        self.assertFalse(applicant.extract_can_be_read)
        with self.assertRaises(UserError):
            applicant.action_extract_document()

    def test_the_document_type_is_a_resume_whatever_the_stage(self):
        """The type says what the document is; the stage says whether to read."""
        applicant = self._applicant()
        later = self.env["hr.recruitment.stage"].search(
            [("fold", "=", False)], order="sequence desc", limit=1
        )
        applicant.stage_id = later

        self.assertEqual(applicant._get_extract_document_type(), "resume")

    def test_reading_is_not_offered_again_once_it_is_done(self):
        with _only(_Stub(_READ)):
            applicant = self._applicant()

            applicant.action_extract_document()

        self.assertEqual(applicant.extract_state, "done")
        self.assertFalse(applicant.extract_can_be_read)
