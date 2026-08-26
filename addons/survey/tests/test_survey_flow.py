from odoo.tests import tagged
from odoo.tests.common import HttpCase

from odoo.addons.survey.tests import common


@tagged("-at_install", "post_install", "functional", "is_query_count")
class TestSurveyFlow(common.TestSurveyCommon, HttpCase):
    def _format_submission_data(self, page, answer_data, additional_post_data):
        post_data = {}
        post_data["page_id"] = page.id
        for question_id, answer_vals in answer_data.items():
            question = page.question_ids.filtered(
                lambda q, qid=question_id: q.id == qid
            )
            post_data.update(
                self._prepare_post_data(question, answer_vals["value"], post_data)
            )
        post_data.update(**additional_post_data)
        return post_data

    def test_flow_public(self):
        with self.with_user("survey_manager"):
            survey = self.env["survey.survey"].create(
                {
                    "title": "Public Survey for Tarte Al Djotte",
                    "access_mode": "public",
                    "users_login_required": False,
                    "questions_layout": "page_per_section",
                }
            )

            page_0 = self.env["survey.question"].create(
                {
                    "is_page": True,
                    "question_type": False,
                    "sequence": 1,
                    "title": "Page1: Your Data",
                    "survey_id": survey.id,
                }
            )
            page0_q0 = self._add_question(
                page_0,
                "What is your name",
                "text_box",
                comments_allowed=False,
                constr_mandatory=True,
                constr_error_msg="Please enter your name",
                survey_id=survey.id,
            )
            page0_q1 = self._add_question(
                page_0,
                "What is your age",
                "numerical_box",
                comments_allowed=False,
                constr_mandatory=True,
                constr_error_msg="Please enter your name",
                survey_id=survey.id,
            )

            page_1 = self.env["survey.question"].create(
                {
                    "is_page": True,
                    "question_type": False,
                    "sequence": 4,
                    "title": "Page2: Tarte Al Djotte",
                    "survey_id": survey.id,
                }
            )
            page1_q0 = self._add_question(
                page_1,
                "What do you like most in our tarte al djotte",
                "multiple_choice",
                labels=[
                    {"value": "The gras"},
                    {"value": "The bette"},
                    {"value": "The tout"},
                    {"value": "The regime is fucked up"},
                ],
                survey_id=survey.id,
            )

        answers = self.env["survey.user_input"].search([("survey_id", "=", survey.id)])
        answer_lines = self.env["survey.user_input.line"].search(
            [("survey_id", "=", survey.id)]
        )
        self.assertEqual(answers, self.env["survey.user_input"])
        self.assertEqual(answer_lines, self.env["survey.user_input.line"])

        r = self._access_start(survey)
        self.assertResponse(r, 200, [survey.title])

        answers = self.env["survey.user_input"].search([("survey_id", "=", survey.id)])
        self.assertEqual(len(answers), 1)
        answer_token = answers.access_token
        self.assertTrue(answer_token)
        self.assertAnswer(answers, "new", self.env["survey.question"])

        r = self._access_page(survey, answer_token)
        self.assertResponse(r, 200)
        self.assertAnswer(answers, "new", self.env["survey.question"])
        csrf_token = self._find_csrf_token(r.text)

        r = self._access_begin(survey, answer_token)
        self.assertResponse(r, 200)

        answer_data = {
            page0_q0.id: {"value": ["Alfred Poilvache"]},
            page0_q1.id: {"value": ["44.0"]},
        }
        post_data = self._format_submission_data(
            page_0,
            answer_data,
            {"csrf_token": csrf_token, "token": answer_token, "button_submit": "next"},
        )
        r = self._access_submit(survey, answer_token, post_data, query_count=45)
        self.assertResponse(r, 200)
        answers.invalidate_recordset()

        self.assertAnswer(answers, "in_progress", page_0)
        self.assertAnswerLines(page_0, answers, answer_data)

        r = self._access_page(survey, answer_token)
        self.assertResponse(r, 200)
        csrf_token = self._find_csrf_token(r.text)

        answer_data = {
            page1_q0.id: {
                "value": [
                    page1_q0.suggested_answer_ids.ids[0],
                    page1_q0.suggested_answer_ids.ids[1],
                ]
            },
        }
        post_data = self._format_submission_data(
            page_1,
            answer_data,
            {"csrf_token": csrf_token, "token": answer_token, "button_submit": "next"},
        )
        r = self._access_submit(survey, answer_token, post_data, query_count=40)
        self.assertResponse(r, 200)
        answers.invalidate_recordset()

        self.assertAnswer(answers, "done", page_1)
        self.assertAnswerLines(page_1, answers, answer_data)
