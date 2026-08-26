import json

from odoo.tests import HttpCase, tagged

from odoo.addons.survey.tests import common


@tagged("post_install", "-at_install", "functional")
class TestTransactionIsolation(common.TestSurveyCommon, HttpCase):
    """A swallowed database error must not poison the rest of the request.

    Swallowing the Python exception does not un-abort a PostgreSQL transaction,
    so every broad handler around ORM work needs a savepoint or the next query
    dies on InFailedSqlTransaction.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.prefill_survey = cls.env["survey.survey"].create(
            {
                "title": "Prefill survey",
                "access_mode": "public",
                "questions_layout": "one_page",
                "question_and_page_ids": [
                    (
                        0,
                        0,
                        {
                            "title": "Scale",
                            "sequence": 1,
                            "question_type": "scale",
                            "scale_min": 0,
                            "scale_max": 10,
                        },
                    ),
                    (
                        0,
                        0,
                        {"title": "Text", "sequence": 2, "question_type": "char_box"},
                    ),
                ],
            }
        )
        cls.scale_question = cls.prefill_survey.question_ids[0]

    def _begin(self, params):
        answer = self.prefill_survey._create_answer(email="prefill@test.com")
        response = self.url_open(
            f"/survey/begin/{self.prefill_survey.access_token}/{answer.access_token}",
            data=json.dumps({"jsonrpc": "2.0", "method": "call", "params": params}),
            headers={"Content-Type": "application/json"},
        )
        return answer, response

    def test_out_of_range_prefill_does_not_500(self):
        """value_scale is int4: 2**31 fails at the database, not in Python."""
        _answer, response = self._begin({f"Q{self.scale_question.id}": str(2**31)})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertNotIn(
            "error",
            payload,
            "an out-of-range prefill must be skipped, not abort the transaction",
        )
        self.assertIn("survey_content", payload["result"][1])

    def test_valid_prefill_still_applies(self):
        answer, response = self._begin({f"Q{self.scale_question.id}": "5"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("error", response.json())
        answer.invalidate_recordset()
        line = answer.user_input_line_ids.filtered(
            lambda ln: ln.question_id == self.scale_question
        )
        self.assertEqual(line.value_scale, 5)

    def test_bad_prefill_does_not_discard_the_good_ones(self):
        """The loop must survive one bad value and keep going."""
        text_question = self.prefill_survey.question_ids[1]
        answer, response = self._begin(
            {
                f"Q{self.scale_question.id}": str(2**31),
                f"Q{text_question.id}": "kept",
            }
        )
        self.assertEqual(response.status_code, 200)
        answer.invalidate_recordset()
        text_line = answer.user_input_line_ids.filtered(
            lambda ln: ln.question_id == text_question
        )
        self.assertEqual(text_line.value_char_box, "kept")

    def test_calculated_fields_actually_compute(self):
        """The broad handler hid a TypeError that killed the feature outright.

        safe_eval in this fork takes no ``nocopy`` argument, so every evaluation
        raised and was swallowed at warning level: a calculated question never
        produced a value.
        """
        survey = self.env["survey.survey"].create(
            {
                "title": "Working calculated survey",
                "access_mode": "public",
                "questions_layout": "one_page",
                "question_and_page_ids": [
                    (
                        0,
                        0,
                        {"title": "A", "sequence": 1, "question_type": "numerical_box"},
                    ),
                    (
                        0,
                        0,
                        {"title": "B", "sequence": 2, "question_type": "numerical_box"},
                    ),
                ],
            }
        )
        q_a, q_b = survey.question_ids
        calc = self.env["survey.question"].create(
            {
                "survey_id": survey.id,
                "title": "Weighted",
                "sequence": 3,
                "question_type": "calculated",
                "calculated_expression": f"Q{q_a.id} * 0.3 + Q{q_b.id} * 0.7",
            }
        )
        answer = survey._create_answer(email="calc-ok@test.com")
        answer._mark_in_progress()
        answer._save_lines(q_a, "10")
        answer._save_lines(q_b, "20")
        answer._evaluate_calculated_fields()
        line = answer.user_input_line_ids.filtered(lambda ln: ln.question_id == calc)
        self.assertTrue(line, "a calculated question must produce a line")
        self.assertAlmostEqual(line.value_numerical_box, 17.0, places=6)
        self.assertFalse(line.skipped)

    def test_calculated_field_failure_leaves_the_cursor_usable(self):
        survey = self.env["survey.survey"].create(
            {
                "title": "Calculated survey",
                "access_mode": "public",
                "questions_layout": "one_page",
                "question_and_page_ids": [
                    (
                        0,
                        0,
                        {"title": "N", "sequence": 1, "question_type": "numerical_box"},
                    ),
                    (
                        0,
                        0,
                        {
                            "title": "Calc",
                            "sequence": 2,
                            "question_type": "calculated",
                            "calculated_expression": "1 / 0",
                        },
                    ),
                ],
            }
        )
        answer = survey._create_answer(email="calc@test.com")
        answer._mark_in_progress()
        answer._save_lines(survey.question_ids[0], "3")
        answer._evaluate_calculated_fields()
        self.assertTrue(
            self.env["survey.survey"].search_count([("id", "=", survey.id)]),
            "the cursor must still be usable after a failed calculated field",
        )
