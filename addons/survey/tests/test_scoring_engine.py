from odoo.tests import tagged

from odoo.addons.survey.tests import common


@tagged('post_install', '-at_install')
class TestSurveyScoringEngine(common.TestSurveyCommon):
    """Score aggregation and the pass/fail threshold on a quiz."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.quiz = cls.env['survey.survey'].create({
            'title': 'Scoring quiz',
            'access_mode': 'public',
            'users_login_required': False,
            'scoring_type': 'scoring_with_answers',
            'scoring_success_min': 50.0,
        })
        cls.page = cls.env['survey.question'].create({
            'title': 'Quiz page',
            'survey_id': cls.quiz.id,
            'is_page': True,
            'sequence': 1,
        })

    def _simple_choice(self, scores, qtype='simple_choice'):
        return self._add_question(
            self.page, f'Q {qtype} {scores}', qtype,
            survey_id=self.quiz.id,
            labels=[{'value': f'A{i}', 'answer_score': s}
                    for i, s in enumerate(scores)],
        )

    def _answer(self):
        return self._add_answer(self.quiz, self.env.user.partner_id)

    def test_simple_choice_counts_only_the_best_answer(self):
        """A single-choice question can only ever yield its top score."""
        question = self._simple_choice([2.0, 5.0])
        answer = self._answer()
        self._add_answer_line(
            question, answer, question.suggested_answer_ids[1].id,
            answer_score=5.0,
        )
        self.assertEqual(answer.scoring_total, 5.0)
        # the maximum possible is 5, so a perfect answer is 100%
        self.assertEqual(answer.scoring_percentage, 100.0)

    def test_multiple_choice_sums_every_positive_answer(self):
        """A multi-choice question can yield the sum of its positive scores."""
        question = self._simple_choice([2.0, 3.0], qtype='multiple_choice')
        answer = self._answer()
        self._add_answer_line(
            question, answer, question.suggested_answer_ids[0].id,
            answer_score=2.0,
        )
        # total possible is 2 + 3 = 5, the respondent scored 2
        self.assertEqual(answer.scoring_total, 2.0)
        self.assertEqual(answer.scoring_percentage, 40.0)

    def test_negative_scores_never_raise_the_ceiling(self):
        """Wrong answers carrying a penalty do not inflate the maximum."""
        question = self._simple_choice([4.0, -4.0])
        answer = self._answer()
        self._add_answer_line(
            question, answer, question.suggested_answer_ids[1].id,
            answer_score=-4.0,
        )
        # ceiling stays 4 and the negative total is clamped to 0%
        self.assertEqual(answer.scoring_total, -4.0)
        self.assertEqual(answer.scoring_percentage, 0)

    def test_unscored_survey_reports_zero(self):
        """With nothing worth points the percentage stays at zero (boundary)."""
        self._simple_choice([0.0, 0.0])
        answer = self._answer()
        self.assertEqual(answer.scoring_total, 0)
        self.assertEqual(answer.scoring_percentage, 0)

    def test_scoring_success_follows_the_threshold(self):
        """The pass flag compares the percentage against the survey minimum."""
        question = self._simple_choice([10.0])
        answer = self._answer()
        line = self._add_answer_line(
            question, answer, question.suggested_answer_ids[0].id,
            answer_score=10.0,
        )
        self.assertTrue(answer.scoring_success)

        # halve the score: 50% still meets a 50% threshold (boundary)
        line.answer_score = 5.0
        self.assertEqual(answer.scoring_percentage, 50.0)
        self.assertTrue(answer.scoring_success)

        # just below it now fails
        line.answer_score = 4.0
        self.assertFalse(answer.scoring_success)
