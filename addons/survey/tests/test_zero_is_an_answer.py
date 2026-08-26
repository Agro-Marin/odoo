import json

from odoo.tests import HttpCase, tagged

from odoo.addons.survey.tests import common


@tagged("post_install", "-at_install", "functional")
class TestZeroIsAnAnswer(common.TestSurveyCommon, HttpCase):
    """A submitted 0 is an answer on every type whose range admits it.

    Four layers used to decide this independently -- the QWeb attribute, the JS
    guard, ``_extract_comment_from_answers`` and ``_get_line_answer_values`` --
    and only ``_is_unanswered`` got it right. These pin the survivors.
    """

    ZERO_IS_VALID = ("numerical_box", "scale", "nps", "slider")

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.zero_survey = cls.env["survey.survey"].create(
            {
                "title": "Zero survey",
                "access_mode": "public",
                "questions_layout": "one_page",
                "question_and_page_ids": [
                    (
                        0,
                        0,
                        {
                            "title": "Num",
                            "sequence": 1,
                            "question_type": "numerical_box",
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "title": "Scale",
                            "sequence": 2,
                            "question_type": "scale",
                            "scale_min": 0,
                            "scale_max": 10,
                        },
                    ),
                    (0, 0, {"title": "Nps", "sequence": 3, "question_type": "nps"}),
                    (
                        0,
                        0,
                        {
                            "title": "Slider",
                            "sequence": 4,
                            "question_type": "slider",
                            "slider_min": 0,
                            "slider_max": 100,
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "title": "Rating",
                            "sequence": 5,
                            "question_type": "rating",
                            "rating_max": 5,
                        },
                    ),
                ],
            }
        )
        cls.questions_by_type = {
            q.question_type: q for q in cls.zero_survey.question_ids
        }

    def _line_for(self, answer, question):
        return answer.user_input_line_ids.filtered(
            lambda line: line.question_id == question
        )

    def test_save_lines_keeps_a_numeric_zero(self):
        for raw in (0, 0.0, "0"):
            for question_type in self.ZERO_IS_VALID:
                question = self.questions_by_type[question_type]
                answer = self.zero_survey._create_answer(
                    email=f"zero-{question_type}@test.com"
                )
                answer._save_lines(question, raw)
                line = self._line_for(answer, question)
                with self.subTest(question_type=question_type, raw=repr(raw)):
                    self.assertTrue(line, "a line must exist for a zero answer")
                    self.assertFalse(
                        line.skipped,
                        f"{question_type} answered with {raw!r} was recorded as skipped",
                    )
                    self.assertTrue(line.answer_type)

    def test_save_lines_still_skips_a_real_blank(self):
        for raw in (False, "", "   ", None):
            question = self.questions_by_type["numerical_box"]
            answer = self.zero_survey._create_answer(email="blank@test.com")
            answer._save_lines(question, raw)
            line = self._line_for(answer, question)
            with self.subTest(raw=repr(raw)):
                self.assertTrue(line.skipped, f"{raw!r} must still count as unanswered")
                self.assertFalse(line.answer_type)

    def test_extract_comment_from_answers_preserves_zero(self):
        """The controller decided this before validation ever ran."""
        from odoo.addons.survey.controllers.main import Survey

        controller = Survey()
        for question_type in self.ZERO_IS_VALID:
            question = self.questions_by_type[question_type]
            with self.subTest(question_type=question_type):
                extracted, comment = controller._extract_comment_from_answers(
                    question, 0
                )
                self.assertEqual(extracted, 0)
                self.assertIsNone(comment)
                self.assertFalse(question._is_unanswered(extracted))

    def test_zero_is_not_a_valid_rating(self):
        """A rating runs 1..N, so 0 must be rejected rather than silently skipped."""
        rating = self.questions_by_type["rating"]
        self.assertTrue(rating._check_answer(0), "rating 0 must be a validation error")
        self.assertTrue(rating._check_answer("0"))
        self.assertFalse(rating._check_answer("1"))

    def test_display_name_of_a_zero_answer_is_not_skipped(self):
        for question_type in self.ZERO_IS_VALID:
            question = self.questions_by_type[question_type]
            answer = self.zero_survey._create_answer(
                email=f"dn-{question_type}@test.com"
            )
            answer._save_lines(question, 0)
            line = self._line_for(answer, question)
            with self.subTest(question_type=question_type):
                self.assertNotEqual(line.display_name, "Skipped")

    def test_nps_counts_a_zero_as_a_detractor(self):
        """The whole point: a lost 0 does not just vanish, it inflates the score."""
        nps = self.questions_by_type["nps"]
        for score in (0, 9, 10):
            answer = self.zero_survey._create_answer(email=f"nps{score}@test.com")
            answer._mark_in_progress()
            answer._save_lines(nps, score)
            answer._mark_done()
        lines = self.env["survey.user_input.line"].search(
            [("question_id", "=", nps.id)]
        )
        summary = nps._prepare_question_statistics(lines)[0]["extra_data"]
        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["detractors"], 1)
        self.assertEqual(summary["nps_score"], 33)

    def test_validation_bounds_of_zero_reach_the_dom(self):
        """QWeb omits a t-att- whose value is falsy, and 0 is falsy."""
        question = self.env["survey.question"].create(
            {
                "survey_id": self.zero_survey.id,
                "title": "Bounded",
                "question_type": "numerical_box",
                "validation_required": True,
                "validation_min_float_value": 0,
                "validation_max_float_value": 100,
            }
        )
        rendered = self.env["ir.qweb"]._render(
            "survey.question_numerical_box",
            {"question": question, "answer_lines": None},
        )
        self.assertIn("data-validation-float-min", rendered)
        self.assertIn("data-validation-float-max", rendered)

    def test_submit_route_keeps_a_json_number_zero(self):
        """/survey/submit is jsonrpc: a JSON number is what a non-browser client sends."""
        answer = self.zero_survey._create_answer(email="rpc@test.com")
        answer._mark_in_progress()
        payload = {
            str(self.questions_by_type[question_type].id): 0
            for question_type in self.ZERO_IS_VALID
        }
        response = self.url_open(
            f"/survey/submit/{self.zero_survey.access_token}/{answer.access_token}",
            data=json.dumps({"jsonrpc": "2.0", "method": "call", "params": payload}),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(response.status_code, 200)
        answer.invalidate_recordset()
        for question_type in self.ZERO_IS_VALID:
            question = self.questions_by_type[question_type]
            line = self._line_for(answer, question)
            with self.subTest(question_type=question_type):
                self.assertTrue(line, f"no line stored for {question_type}")
                self.assertFalse(
                    line.skipped, f"{question_type} zero was stored as skipped"
                )
