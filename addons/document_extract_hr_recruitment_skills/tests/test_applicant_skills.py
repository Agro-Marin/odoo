import contextlib

from odoo.tests.common import TransactionCase, tagged

from odoo.addons.document_extract.tools import FREE, BaseExtractor
from odoo.addons.document_extract.tools import extractors as registry


class _Stub(BaseExtractor):
    name = "cv_skills_test_stub"
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


@tagged("post_install", "-at_install")
class TestApplicantSkillExtraction(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.job = cls.env["hr.job"].create({"name": "Analyst"})
        cls.skill_type = cls.env["hr.skill.type"].create({"name": "Languages"})
        cls.level = cls.env["hr.skill.level"].create(
            {
                "name": "Fluent",
                "skill_type_id": cls.skill_type.id,
                "level_progress": 100,
                "default_level": True,
            }
        )
        cls.python = cls.env["hr.skill"].create(
            {"name": "Python", "skill_type_id": cls.skill_type.id}
        )
        cls.spanish = cls.env["hr.skill"].create(
            {"name": "Spanish", "skill_type_id": cls.skill_type.id}
        )

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

    def _read(self, skills):
        return {"full_name": "Ada Lovelace", "skills": skills}

    def test_it_attaches_a_skill_the_catalogue_carries(self):
        with _only(_Stub(self._read(["Python"]))):
            applicant = self._applicant()

            applicant.action_extract_document()

        self.assertIn(self.python, applicant.applicant_skill_ids.skill_id)

    def test_it_matches_regardless_of_case(self):
        with _only(_Stub(self._read(["pYTHON"]))):
            applicant = self._applicant()

            applicant.action_extract_document()

        self.assertIn(self.python, applicant.applicant_skill_ids.skill_id)

    def test_it_does_not_invent_a_skill_the_catalogue_lacks(self):
        with _only(_Stub(self._read(["Sorcery"]))):
            applicant = self._applicant()

            applicant.action_extract_document()

        self.assertFalse(applicant.applicant_skill_ids)
        self.assertFalse(self.env["hr.skill"].search([("name", "=", "Sorcery")]))

    def test_it_reads_a_list_of_dicts_as_well_as_of_strings(self):
        with _only(_Stub(self._read([{"name": "Spanish"}]))):
            applicant = self._applicant()

            applicant.action_extract_document()

        self.assertIn(self.spanish, applicant.applicant_skill_ids.skill_id)

    def test_it_leaves_a_skill_the_applicant_already_has_alone(self):
        other_level = self.env["hr.skill.level"].create(
            {
                "name": "Basic",
                "skill_type_id": self.skill_type.id,
                "level_progress": 10,
            }
        )
        applicant = self._applicant()
        self.env["hr.applicant.skill"].create(
            {
                "applicant_id": applicant.id,
                "skill_id": self.python.id,
                "skill_type_id": self.skill_type.id,
                "skill_level_id": other_level.id,
            }
        )

        with _only(_Stub(self._read(["Python"]))):
            applicant.action_extract_document()

        self.assertEqual(len(applicant.applicant_skill_ids), 1)
        self.assertEqual(applicant.applicant_skill_ids.skill_level_id, other_level)

    def test_a_cv_naming_no_skills_changes_nothing(self):
        with _only(_Stub({"full_name": "Ada Lovelace"})):
            applicant = self._applicant()

            applicant.action_extract_document()

        self.assertFalse(applicant.applicant_skill_ids)
