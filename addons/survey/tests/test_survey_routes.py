from odoo.tests import HttpCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestSurveyStartRoutes(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.survey = cls.env["survey.survey"].create(
            {
                "title": "Route survey",
                "access_mode": "public",
                "users_login_required": False,
            }
        )
        cls.env["survey.question"].create(
            {
                "title": "Say something",
                "survey_id": cls.survey.id,
                "question_type": "text_box",
            }
        )

    def _answers(self):
        return self.env["survey.user_input"].search(
            [("survey_id", "=", self.survey.id)],
        )

    def test_start_public_survey_creates_answer(self):
        before = len(self._answers())
        res = self.url_open(f"/survey/start/{self.survey.access_token}")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(self._answers()), before + 1)

    def test_start_archived_survey_creates_nothing(self):
        self.survey.action_archive()
        res = self.url_open(f"/survey/start/{self.survey.access_token}")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(self._answers())
        self.assertNotIn("Say something", res.text)

    def test_start_with_unknown_token_creates_nothing(self):
        res = self.url_open("/survey/start/not-a-real-survey-token")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(self._answers())

    def test_manager_test_entry_redirects_to_start(self):
        new_test_user(
            self.env,
            login="survey_mgr_routes",
            groups="base.group_user,survey.group_survey_manager",
        )
        self.authenticate("survey_mgr_routes", "survey_mgr_routes")
        res = self.url_open(f"/survey/test/{self.survey.access_token}")
        self.assertEqual(res.status_code, 200)
        self.assertIn(f"/survey/{self.survey.access_token}/", res.url)
        test_answers = self._answers().filtered("test_entry")
        self.assertTrue(test_answers)


@tagged("post_install", "-at_install")
class TestSurveyPrintRoutes(HttpCase):
    """`/survey/print` on a survey scored without answers.

    The participant's own answers and the *correct* answers are two different
    things: the scoring type hides the latter, never the former.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.survey = cls.env["survey.survey"].create(
            {
                "title": "Print survey",
                "access_mode": "public",
                "users_login_required": False,
                "scoring_type": "scoring_without_answers",
            }
        )
        cls.char_question = cls.env["survey.question"].create(
            {
                "title": "Your favourite colour",
                "survey_id": cls.survey.id,
                "question_type": "char_box",
                "sequence": 1,
            }
        )
        cls.numerical_question = cls.env["survey.question"].create(
            {
                "title": "How many legs has a spider",
                "survey_id": cls.survey.id,
                "question_type": "numerical_box",
                "sequence": 2,
                "answer_numerical_box": 8.0,
                "answer_score": 5.0,
            }
        )
        cls.answer = cls.env["survey.user_input"].create({"survey_id": cls.survey.id})
        cls.env["survey.user_input.line"].create(
            [
                {
                    "user_input_id": cls.answer.id,
                    "question_id": cls.char_question.id,
                    "answer_type": "char_box",
                    "value_char_box": "Cerulean",
                },
                {
                    "user_input_id": cls.answer.id,
                    "question_id": cls.numerical_question.id,
                    "answer_type": "numerical_box",
                    "value_numerical_box": 6.0,
                },
            ]
        )

    def _print(self):
        res = self.url_open(
            f"/survey/print/{self.survey.access_token}"
            f"?answer_token={self.answer.access_token}"
        )
        self.assertEqual(res.status_code, 200)
        return res.text

    def test_print_shows_the_participant_own_answers(self):
        self.assertIn("Cerulean", self._print())

    def test_print_hides_the_correct_answer(self):
        body = self._print()
        self.assertNotIn("The correct answer was", body)
        self.assertNotIn("bg-danger", body)
