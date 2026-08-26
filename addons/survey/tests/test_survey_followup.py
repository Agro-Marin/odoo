from odoo import Command
from odoo.tests import tagged

from .common import TestSurveyCommon


@tagged("post_install", "-at_install")
class TestSurveyFollowupRules(TestSurveyCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.survey = cls.env["survey.survey"].create(
            {
                "title": "Followup survey",
                "scoring_type": "scoring_with_answers",
                "scoring_success_min": 50.0,
            },
        )
        cls.question = cls.env["survey.question"].create(
            {
                "survey_id": cls.survey.id,
                "title": "Q1",
                "sequence": 1,
                "question_type": "simple_choice",
                "suggested_answer_ids": [
                    Command.create(
                        {"value": "Good", "is_correct": True, "answer_score": 10}
                    ),
                    Command.create({"value": "Bad", "answer_score": 0}),
                ],
            },
        )
        cls.template = cls.env["mail.template"].create(
            {
                "name": "Followup template",
                "model_id": cls.env["ir.model"]._get_id("survey.user_input"),
                "subject": "Your result",
                "email_to": "{{ object.email }}",
                "body_html": "<p>score</p>",
            },
        )

    def _make_rule(self, name, **kwargs):
        return self.env["survey.followup.rule"].create(
            {
                "survey_id": self.survey.id,
                "name": name,
                "mail_template_id": self.template.id,
                **kwargs,
            },
        )

    def _make_input(self, correct):
        user_input = self._add_answer(
            self.survey, self.survey_user.partner_id, email="followup@test.example.com"
        )
        answer = self.question.suggested_answer_ids.filtered(
            lambda a: a.is_correct is correct
        )[:1]
        self._add_answer_line(self.question, user_input, answer.id)
        return user_input

    def test_evaluate_condition_matrix(self):
        passed = self._make_input(correct=True)
        failed = self._make_input(correct=False)
        self.assertEqual(passed.scoring_percentage, 100.0)
        self.assertEqual(failed.scoring_percentage, 0.0)

        always = self._make_rule("always", condition_type="always")
        in_range = self._make_rule(
            "range", condition_type="score_range", score_min=50.0, score_max=100.0
        )
        on_passed = self._make_rule("passed", condition_type="passed")
        on_failed = self._make_rule("failed", condition_type="failed")

        self.assertTrue(always._evaluate(passed))
        self.assertTrue(always._evaluate(failed))
        self.assertTrue(in_range._evaluate(passed))
        self.assertFalse(in_range._evaluate(failed))
        self.assertTrue(on_passed._evaluate(passed))
        self.assertFalse(on_passed._evaluate(failed))
        self.assertTrue(on_failed._evaluate(failed))
        self.assertFalse(on_failed._evaluate(passed))

    def test_execute_sends_mail_only_when_condition_met(self):
        passed = self._make_input(correct=True)
        failed = self._make_input(correct=False)
        rule = self._make_rule("on pass", condition_type="passed")
        Mail = self.env["mail.mail"].sudo()
        before = Mail.search_count([])

        rule._execute(passed)
        self.assertEqual(Mail.search_count([]), before + 1)

        rule._execute(failed)
        self.assertEqual(Mail.search_count([]), before + 1)
