from odoo.tests import tagged

from odoo.addons.survey.tests import common


@tagged('post_install', '-at_install')
class TestConditionalValueTriggers(common.TestSurveyCommon):
    """Value-based conditional display of questions."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.form = cls.env['survey.survey'].create({
            'title': 'Conditional survey',
            'access_mode': 'public',
            'users_login_required': False,
        })
        cls.age = cls.env['survey.question'].create({
            'title': 'Your age',
            'survey_id': cls.form.id,
            'question_type': 'numerical_box',
            'sequence': 1,
        })
        cls.city = cls.env['survey.question'].create({
            'title': 'Your city',
            'survey_id': cls.form.id,
            'question_type': 'char_box',
            'sequence': 2,
        })

    def _conditional(self, trigger, operator, value, sequence=9):
        return self.env['survey.question'].create({
            'title': f'Shown when {operator} {value}',
            'survey_id': self.form.id,
            'question_type': 'char_box',
            'sequence': sequence,
            'triggering_question_id': trigger.id,
            'triggering_operator': operator,
            'triggering_value': value,
        })

    def _answer_with(self, question, value, field='value_numerical_box'):
        answer = self.env['survey.user_input'].create({
            'survey_id': self.form.id,
        })
        self.env['survey.user_input.line'].create({
            'user_input_id': answer.id,
            'question_id': question.id,
            'answer_type': 'numerical_box' if field.endswith('numerical_box')
            else 'char_box',
            field: value,
            'skipped': False,
        })
        return answer

    def _empty_answer(self):
        return self.env['survey.user_input'].create({'survey_id': self.form.id})

    def test_numeric_operators(self):
        """Each numeric operator compares the answer against the threshold."""
        answer = self._answer_with(self.age, 18)
        cases = [
            ('eq', '18', True), ('eq', '20', False),
            ('neq', '20', True), ('neq', '18', False),
            ('gt', '17', True), ('gt', '18', False),
            ('gte', '18', True), ('gte', '19', False),
            ('lt', '19', True), ('lt', '18', False),
            ('lte', '18', True), ('lte', '17', False),
        ]
        for operator, threshold, expected in cases:
            question = self._conditional(self.age, operator, threshold)
            with self.subTest(operator=operator, threshold=threshold):
                self.assertEqual(
                    answer._evaluate_value_trigger(question), expected,
                )

    def test_string_operators(self):
        """Text answers compare case-insensitively, including contains."""
        answer = self._answer_with(self.city, 'Guadalajara', field='value_char_box')
        cases = [
            ('eq', 'guadalajara', True), ('eq', 'Monterrey', False),
            ('neq', 'Monterrey', True), ('neq', 'GUADALAJARA', False),
            ('contains', 'lajara', True), ('contains', 'Puebla', False),
        ]
        for operator, threshold, expected in cases:
            question = self._conditional(self.city, operator, threshold)
            with self.subTest(operator=operator, threshold=threshold):
                self.assertEqual(
                    answer._evaluate_value_trigger(question), expected,
                )

    def test_answered_and_not_answered_operators(self):
        """Presence operators do not look at the value at all."""
        answered = self._answer_with(self.age, 30)
        blank = self._empty_answer()

        is_answered = self._conditional(self.age, 'is_answered', '')
        self.assertTrue(answered._evaluate_value_trigger(is_answered))
        self.assertFalse(blank._evaluate_value_trigger(is_answered))

        not_answered = self._conditional(self.age, 'is_not_answered', '')
        self.assertFalse(answered._evaluate_value_trigger(not_answered))
        self.assertTrue(blank._evaluate_value_trigger(not_answered))

    def test_unanswered_trigger_blocks_value_operators(self):
        """With no answer to compare, a value operator cannot be met."""
        blank = self._empty_answer()
        question = self._conditional(self.age, 'gt', '10')
        self.assertFalse(blank._evaluate_value_trigger(question))

    def test_non_numeric_threshold_is_refused(self):
        """A threshold that cannot be parsed never matches (negative)."""
        answer = self._answer_with(self.age, 18)
        question = self._conditional(self.age, 'gt', 'eighteen')
        self.assertFalse(answer._evaluate_value_trigger(question))

    def test_unknown_operator_never_matches(self):
        """An operator outside the mapping defaults to not shown."""
        answer = self._answer_with(self.age, 18)
        question = self._conditional(self.age, 'gt', '10')
        question.triggering_operator = False
        self.assertFalse(answer._evaluate_value_trigger(question))

    def test_inactive_questions_hide_unmet_conditionals(self):
        """A conditional question stays hidden while its trigger is unmet."""
        answer = self._answer_with(self.age, 18)
        shown = self._conditional(self.age, 'gte', '18', sequence=10)
        hidden = self._conditional(self.age, 'gte', '65', sequence=11)

        inactive = answer._get_inactive_conditional_questions()
        self.assertIn(hidden, inactive)
        self.assertNotIn(shown, inactive)
