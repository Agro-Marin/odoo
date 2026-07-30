"""Tests for the survey extensions on res.lang and res.partner."""

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import TestSurveyCommon


@tagged("post_install", "-at_install")
class TestSurveyLangDeactivation(TestSurveyCommon):
    """Language deactivation must not orphan surveys or their answers."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.lang_en = cls.env.ref("base.lang_en")
        cls.lang_fr = cls.env["res.lang"]._activate_lang("fr_FR")

    def test_deactivating_sole_survey_language_rejected(self):
        """A language that is a survey's only language cannot be disabled."""
        survey = self.env["survey.survey"].create(
            {
                "title": "FR only survey",
                "lang_ids": [Command.set(self.lang_fr.ids)],
            },
        )
        with self.assertRaises(UserError) as cm:
            self.lang_fr.active = False
        self.assertIn(survey.title, str(cm.exception))

    def test_deactivating_one_of_many_unlinks_and_clears_answers(self):
        """Disabling one of several languages unlinks it and clears answers."""
        survey = self.env["survey.survey"].create(
            {
                "title": "Bilingual survey",
                "lang_ids": [Command.set((self.lang_en | self.lang_fr).ids)],
            },
        )
        user_input = self.env["survey.user_input"].create(
            {"survey_id": survey.id, "lang_id": self.lang_fr.id},
        )

        self.lang_fr.active = False

        self.assertEqual(survey.lang_ids, self.lang_en)
        self.assertFalse(user_input.lang_id)


@tagged("post_install", "-at_install")
class TestPartnerCertifications(TestSurveyCommon):
    """Certification counters and their smart-button action on partners."""

    def test_certification_counts_and_action_domain(self):
        company = self.env["res.partner"].create(
            {"name": "Cert company", "is_company": True},
        )
        child = self.env["res.partner"].create(
            {"name": "Cert employee", "parent_id": company.id},
        )
        survey = self.env["survey.survey"].create(
            {
                "title": "Cert survey",
                "scoring_type": "scoring_with_answers",
                "scoring_success_min": 50.0,
            },
        )
        question = self.env["survey.question"].create(
            {
                "survey_id": survey.id,
                "title": "Q1",
                "sequence": 1,
                "question_type": "simple_choice",
                "suggested_answer_ids": [
                    Command.create(
                        {"value": "Right", "is_correct": True, "answer_score": 10}
                    ),
                ],
            },
        )
        user_input = self._add_answer(survey, child)
        self._add_answer_line(question, user_input, question.suggested_answer_ids[0].id)
        self.assertTrue(user_input.scoring_success)

        self.assertEqual(child.certifications_count, 1)
        self.assertEqual(company.certifications_count, 0)
        self.assertEqual(company.certifications_company_count, 1)

        action = company.action_view_certifications()
        self.assertIn(("scoring_success", "=", True), action["domain"])
