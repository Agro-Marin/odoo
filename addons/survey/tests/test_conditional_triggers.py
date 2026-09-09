from odoo.fields import Command
from odoo.tests import tagged

from odoo.addons.survey.tests import common


@tagged("post_install", "-at_install")
class TestConditionalValueTriggers(common.TestSurveyCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.form = cls.env["survey.survey"].create(
            {
                "title": "Conditional survey",
                "access_mode": "public",
                "users_login_required": False,
            }
        )
        cls.age = cls.env["survey.question"].create(
            {
                "title": "Your age",
                "survey_id": cls.form.id,
                "question_type": "numerical_box",
                "sequence": 1,
            }
        )
        cls.city = cls.env["survey.question"].create(
            {
                "title": "Your city",
                "survey_id": cls.form.id,
                "question_type": "char_box",
                "sequence": 2,
            }
        )

    def _conditional(self, trigger, operator, value, sequence=9):
        return self.env["survey.question"].create(
            {
                "title": f"Shown when {operator} {value}",
                "survey_id": self.form.id,
                "question_type": "char_box",
                "sequence": sequence,
                "triggering_question_id": trigger.id,
                "triggering_operator": operator,
                "triggering_value": value,
            }
        )

    def _answer_with(self, question, value, field="value_numerical_box"):
        answer = self.env["survey.user_input"].create(
            {
                "survey_id": self.form.id,
            }
        )
        self.env["survey.user_input.line"].create(
            {
                "user_input_id": answer.id,
                "question_id": question.id,
                "answer_type": "numerical_box"
                if field.endswith("numerical_box")
                else "char_box",
                field: value,
                "skipped": False,
            }
        )
        return answer

    def _empty_answer(self):
        return self.env["survey.user_input"].create({"survey_id": self.form.id})

    def test_numeric_operators(self):
        answer = self._answer_with(self.age, 18)
        cases = [
            ("eq", "18", True),
            ("eq", "20", False),
            ("neq", "20", True),
            ("neq", "18", False),
            ("gt", "17", True),
            ("gt", "18", False),
            ("gte", "18", True),
            ("gte", "19", False),
            ("lt", "19", True),
            ("lt", "18", False),
            ("lte", "18", True),
            ("lte", "17", False),
        ]
        for operator, threshold, expected in cases:
            question = self._conditional(self.age, operator, threshold)
            with self.subTest(operator=operator, threshold=threshold):
                self.assertEqual(
                    answer._evaluate_value_trigger(question),
                    expected,
                )

    def test_string_operators(self):
        answer = self._answer_with(self.city, "Guadalajara", field="value_char_box")
        cases = [
            ("eq", "guadalajara", True),
            ("eq", "Monterrey", False),
            ("neq", "Monterrey", True),
            ("neq", "GUADALAJARA", False),
            ("contains", "lajara", True),
            ("contains", "Puebla", False),
        ]
        for operator, threshold, expected in cases:
            question = self._conditional(self.city, operator, threshold)
            with self.subTest(operator=operator, threshold=threshold):
                self.assertEqual(
                    answer._evaluate_value_trigger(question),
                    expected,
                )

    def test_answered_and_not_answered_operators(self):
        answered = self._answer_with(self.age, 30)
        blank = self._empty_answer()

        is_answered = self._conditional(self.age, "is_answered", "")
        self.assertTrue(answered._evaluate_value_trigger(is_answered))
        self.assertFalse(blank._evaluate_value_trigger(is_answered))

        not_answered = self._conditional(self.age, "is_not_answered", "")
        self.assertFalse(answered._evaluate_value_trigger(not_answered))
        self.assertTrue(blank._evaluate_value_trigger(not_answered))

    def test_unanswered_trigger_blocks_value_operators(self):
        blank = self._empty_answer()
        question = self._conditional(self.age, "gt", "10")
        self.assertFalse(blank._evaluate_value_trigger(question))

    def test_non_numeric_threshold_is_refused(self):
        answer = self._answer_with(self.age, 18)
        question = self._conditional(self.age, "gt", "eighteen")
        self.assertFalse(answer._evaluate_value_trigger(question))

    def test_unknown_operator_never_matches(self):
        answer = self._answer_with(self.age, 18)
        question = self._conditional(self.age, "gt", "10")
        question.triggering_operator = False
        self.assertFalse(answer._evaluate_value_trigger(question))

    def test_inactive_questions_hide_unmet_conditionals(self):
        answer = self._answer_with(self.age, 18)
        shown = self._conditional(self.age, "gte", "18", sequence=10)
        hidden = self._conditional(self.age, "gte", "65", sequence=11)

        inactive = answer._get_inactive_conditional_questions()
        self.assertIn(hidden, inactive)
        self.assertNotIn(shown, inactive)


@tagged("post_install", "-at_install")
class TestSkippedFlowConditionals(common.TestSurveyCommon):
    """Conditionals a participant turns on *while* replaying skipped questions.

    In roaming mode the survey comes back to the mandatory questions that were
    left blank. Answering one of them can switch a conditional question on, and
    the participant has by definition never been offered that question yet, so
    the replay has to pick it up.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.form = cls.env["survey.survey"].create(
            {
                "title": "Roaming survey",
                "access_mode": "public",
                "users_login_required": False,
                "questions_layout": "page_per_question",
                "users_can_go_back": True,
            }
        )
        cls.colour = cls.env["survey.question"].create(
            {
                "title": "Your favourite colour",
                "survey_id": cls.form.id,
                "question_type": "simple_choice",
                "sequence": 1,
                "constr_mandatory": True,
                "suggested_answer_ids": [
                    Command.create({"value": "Blue"}),
                    Command.create({"value": "Red"}),
                ],
            }
        )
        cls.blue = cls.colour.suggested_answer_ids[0]
        cls.age = cls.env["survey.question"].create(
            {
                "title": "Your age",
                "survey_id": cls.form.id,
                "question_type": "numerical_box",
                "sequence": 2,
                "constr_mandatory": True,
            }
        )
        cls.city = cls.env["survey.question"].create(
            {
                "title": "Your city",
                "survey_id": cls.form.id,
                "question_type": "char_box",
                "sequence": 3,
            }
        )
        # Triggered by a chosen answer -- the only shape upstream knows about.
        cls.why_blue = cls.env["survey.question"].create(
            {
                "title": "Why blue?",
                "survey_id": cls.form.id,
                "question_type": "char_box",
                "sequence": 4,
                "triggering_answer_ids": [Command.link(cls.blue.id)],
            }
        )
        # Triggered by the *value* of another answer -- our own extension.
        cls.pension = cls.env["survey.question"].create(
            {
                "title": "Are you retired?",
                "survey_id": cls.form.id,
                "question_type": "char_box",
                "sequence": 5,
                "triggering_question_id": cls.age.id,
                "triggering_operator": "gte",
                "triggering_value": "65",
            }
        )

    def _answer(self):
        return self.env["survey.user_input"].create({"survey_id": self.form.id})

    def _skip(self, answer, question):
        return self.env["survey.user_input.line"].create(
            {
                "user_input_id": answer.id,
                "question_id": question.id,
                "answer_type": None,
                "skipped": True,
            }
        )

    def _reply(self, line, **values):
        line.write(dict(values, skipped=False))

    def test_answer_trigger_reached_from_the_skipped_flow(self):
        answer = self._answer()
        skipped_colour = self._skip(answer, self.colour)
        self._skip(answer, self.age)

        self.assertEqual(
            answer._get_skipped_questions(),
            self.colour | self.age,
            "both mandatory questions were left blank",
        )

        # The participant comes back and picks Blue, which turns "Why blue?" on.
        self._reply(
            skipped_colour, answer_type="suggestion", suggested_answer_id=self.blue.id
        )
        answer.last_displayed_page_id = self.colour

        self.assertEqual(
            answer._get_skipped_questions(),
            self.age | self.why_blue,
            "the freshly triggered question joins the questions still to answer",
        )
        self.assertEqual(answer._get_next_skipped_page_or_question(), self.age)

    def test_value_trigger_reached_from_the_skipped_flow(self):
        answer = self._answer()
        skipped_age = self._skip(answer, self.age)

        # Answering 70 turns "Are you retired?" on through a value trigger, which
        # carries no `triggering_answer_ids` at all.
        self._reply(skipped_age, answer_type="numerical_box", value_numerical_box=70.0)
        answer.last_displayed_page_id = self.age

        self.assertEqual(answer._get_skipped_questions(), self.pension)
        self.assertEqual(answer._get_next_skipped_page_or_question(), self.pension)

    def test_untriggered_conditionals_stay_out_of_the_skipped_flow(self):
        answer = self._answer()
        skipped_colour = self._skip(answer, self.colour)
        skipped_age = self._skip(answer, self.age)

        self._reply(
            skipped_colour,
            answer_type="suggestion",
            suggested_answer_id=self.colour.suggested_answer_ids[1].id,
        )
        self._reply(skipped_age, answer_type="numerical_box", value_numerical_box=30.0)

        self.assertFalse(
            answer._get_skipped_questions(),
            "Red and 30 trigger nothing, so the replay is over",
        )
        self.assertFalse(answer._get_next_skipped_page_or_question())

    def test_a_conditional_already_shown_is_not_replayed(self):
        answer = self._answer()
        skipped_colour = self._skip(answer, self.colour)
        self._reply(
            skipped_colour, answer_type="suggestion", suggested_answer_id=self.blue.id
        )
        # The participant was offered "Why blue?" and skipped it: it is not
        # mandatory, so it must not come back a second time.
        self._skip(answer, self.why_blue)

        self.assertFalse(answer._get_skipped_questions())
