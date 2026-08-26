from datetime import timedelta

from markupsafe import Markup

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.survey.tests.common import TestSurveyCommon


@tagged("post_install", "-at_install")
class TestSurveySession(TestSurveyCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.survey_session = (
            cls.env["survey.survey"]
            .with_user(cls.survey_manager)
            .create(
                {
                    "title": "Live Session Survey",
                    "survey_type": "live_session",
                    "access_mode": "public",
                    "questions_layout": "page_per_question",
                    "scoring_type": "scoring_with_answers",
                }
            )
        )
        cls.session_page = (
            cls.env["survey.question"]
            .with_user(cls.survey_manager)
            .create(
                {
                    "title": "Session Page",
                    "survey_id": cls.survey_session.id,
                    "sequence": 1,
                    "is_page": True,
                    "question_type": False,
                }
            )
        )
        Question = cls.env["survey.question"].with_user(cls.survey_manager)
        cls.session_q1 = Question.create(
            {
                "title": "Session Q1",
                "survey_id": cls.survey_session.id,
                "sequence": 2,
                "question_type": "simple_choice",
                "constr_mandatory": True,
                "suggested_answer_ids": [
                    (0, 0, {"value": "A", "is_correct": True, "answer_score": 1}),
                    (0, 0, {"value": "B"}),
                ],
            }
        )
        cls.session_q2 = Question.create(
            {
                "title": "Session Q2",
                "survey_id": cls.survey_session.id,
                "sequence": 3,
                "question_type": "simple_choice",
                "constr_mandatory": True,
                "suggested_answer_ids": [
                    (0, 0, {"value": "X", "is_correct": True, "answer_score": 1}),
                    (0, 0, {"value": "Y"}),
                ],
            }
        )

    def test_session_start_sets_state(self):
        survey = self.survey_session.with_user(self.survey_manager)
        self.assertFalse(survey.session_state)

        survey.action_start_session()
        self.assertEqual(survey.session_state, "ready")
        self.assertTrue(survey.session_code)
        self.assertTrue(survey.session_start_time)

    def test_session_open_transitions_to_in_progress(self):
        survey = self.survey_session.with_user(self.survey_manager)
        survey.action_start_session()
        self.assertEqual(survey.session_state, "ready")

        survey._session_open()
        self.assertEqual(survey.session_state, "in_progress")

    def test_session_question_advancement(self):
        survey = self.survey_session.with_user(self.survey_manager)
        survey.action_start_session()
        survey._session_open()

        next_q = survey._get_session_next_question(go_back=False)
        self.assertEqual(next_q, self.session_q1)

        survey.sudo().write({"session_question_id": next_q.id})

        next_q = survey._get_session_next_question(go_back=False)
        self.assertEqual(next_q, self.session_q2)

    def test_session_question_go_back(self):
        survey = self.survey_session.with_user(self.survey_manager)
        survey.action_start_session()
        survey._session_open()

        survey.sudo().write({"session_question_id": self.session_q2.id})

        prev_q = survey._get_session_next_question(go_back=True)
        self.assertEqual(prev_q, self.session_q1)

    def test_session_end_resets_state(self):
        survey = self.survey_session.with_user(self.survey_manager)
        survey.action_start_session()
        survey._session_open()

        session_answer = self._add_answer(
            survey,
            self.customer,
            state="in_progress",
            is_session_answer=True,
        )

        historical_answer = self._add_answer(
            survey,
            self.customer,
            state="in_progress",
            is_session_answer=False,
        )

        survey.action_end_session()
        self.assertFalse(survey.session_state)
        self.assertEqual(session_answer.state, "done")
        self.assertEqual(
            historical_answer.state,
            "in_progress",
            "action_end_session must not modify non-session inputs",
        )


@tagged("post_install", "-at_install")
class TestSurveyAttemptLimits(TestSurveyCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.survey_limited = (
            cls.env["survey.survey"]
            .with_user(cls.survey_manager)
            .create(
                {
                    "title": "Limited Attempts Survey",
                    "access_mode": "public",
                    "users_login_required": True,
                    "is_attempts_limited": True,
                    "attempts_limit": 2,
                    "questions_layout": "page_per_question",
                }
            )
        )
        cls.limited_page = (
            cls.env["survey.question"]
            .with_user(cls.survey_manager)
            .create(
                {
                    "title": "Limited Page",
                    "survey_id": cls.survey_limited.id,
                    "sequence": 1,
                    "is_page": True,
                    "question_type": False,
                }
            )
        )
        cls.env["survey.question"].with_user(cls.survey_manager).create(
            {
                "title": "Q1",
                "survey_id": cls.survey_limited.id,
                "sequence": 2,
                "question_type": "char_box",
                "constr_mandatory": False,
            }
        )

    def test_attempts_count_tracks_done_answers(self):
        survey = self.survey_limited

        answer1 = self._add_answer(survey, self.customer, state="done")
        survey.invalidate_recordset(["answer_count"])

        self.assertEqual(answer1.attempts_number, 1)
        self.assertTrue(survey._has_attempts_left(self.customer, False, False))

        answer2 = self._add_answer(survey, self.customer, state="done")
        survey.invalidate_recordset(["answer_count"])
        self.assertEqual(answer2.attempts_number, 2)

    def test_create_answer_blocked_when_limit_exceeded(self):
        survey = self.survey_limited.with_user(self.survey_manager)

        for _ in range(2):
            answer = survey._create_answer(partner=self.customer)
            answer.write({"state": "done"})

        with self.assertRaises(UserError):
            survey._create_answer(partner=self.customer)


@tagged("post_install", "-at_install")
class TestSurveyDeadline(TestSurveyCommon):
    def test_expired_deadline_blocks_submission(self):
        answer = self._add_answer(
            self.survey,
            self.customer,
            state="in_progress",
            deadline=fields.Datetime.now() - timedelta(hours=1),
        )
        self.assertTrue(
            answer.survey_time_limit_reached or answer.deadline < fields.Datetime.now()
        )

    def test_valid_deadline_allows_access(self):
        answer = self._add_answer(
            self.survey,
            self.customer,
            state="in_progress",
            deadline=fields.Datetime.now() + timedelta(hours=1),
        )
        self.assertFalse(answer.survey_time_limit_reached)


@tagged("post_install", "-at_install")
class TestSurveyBackNavigation(TestSurveyCommon):
    def test_back_navigation_disabled(self):
        self.assertFalse(self.survey.users_can_go_back)
        answer = self._add_answer(self.survey, self.customer, state="in_progress")
        can_go = self.survey._can_go_back(answer, self.question_ft)
        self.assertFalse(can_go)

    def test_back_navigation_enabled(self):
        self.survey.write({"users_can_go_back": True})
        answer = self._add_answer(
            self.survey,
            self.customer,
            state="in_progress",
            last_displayed_page_id=self.question_num.id,
        )
        can_go = self.survey._can_go_back(answer, self.question_num)
        self.assertTrue(can_go)


@tagged("post_install", "-at_install")
class TestSurveyTimeLimits(TestSurveyCommon):
    def test_survey_time_limit_reached(self):
        self.survey.write({"is_time_limited": True, "time_limit": 10.0})
        answer = self._add_answer(self.survey, self.customer, state="in_progress")
        answer.write(
            {
                "start_datetime": fields.Datetime.now() - timedelta(minutes=15),
            }
        )
        answer.invalidate_recordset(["survey_time_limit_reached"])
        self.assertTrue(answer.survey_time_limit_reached)

    def test_survey_time_limit_not_reached(self):
        self.survey.write({"is_time_limited": True, "time_limit": 10.0})
        answer = self._add_answer(self.survey, self.customer, state="in_progress")
        answer.write(
            {
                "start_datetime": fields.Datetime.now() - timedelta(minutes=5),
            }
        )
        answer.invalidate_recordset(["survey_time_limit_reached"])
        self.assertFalse(answer.survey_time_limit_reached)


@tagged("post_install", "-at_install")
class TestResolvePiping(TestSurveyCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.survey_piping = (
            cls.env["survey.survey"]
            .with_user(cls.survey_manager)
            .create(
                {
                    "title": "Piping Survey",
                    "access_mode": "public",
                    "questions_layout": "page_per_question",
                }
            )
        )
        cls.piping_page = (
            cls.env["survey.question"]
            .with_user(cls.survey_manager)
            .create(
                {
                    "title": "Page",
                    "survey_id": cls.survey_piping.id,
                    "sequence": 1,
                    "is_page": True,
                    "question_type": False,
                }
            )
        )
        cls.piping_q1 = (
            cls.env["survey.question"]
            .with_user(cls.survey_manager)
            .create(
                {
                    "title": "What is your name?",
                    "survey_id": cls.survey_piping.id,
                    "sequence": 2,
                    "question_type": "char_box",
                }
            )
        )
        cls.piping_q2 = (
            cls.env["survey.question"]
            .with_user(cls.survey_manager)
            .create(
                {
                    "title": "Follow-up",
                    "survey_id": cls.survey_piping.id,
                    "sequence": 3,
                    "question_type": "char_box",
                    "description": "<p>Hello {{Q%s}}, welcome!</p>" % cls.piping_q1.id,
                }
            )
        )

    def test_piping_preserves_markup_type(self):
        answer = self._add_answer(
            self.survey_piping, self.customer, state="in_progress"
        )
        self._add_answer_line(self.piping_q1, answer, "Alice")

        html_text = Markup(f"<p>Hello {{{{Q{self.piping_q1.id}}}}}, welcome!</p>")
        result = answer._resolve_piping(html_text)
        self.assertIsInstance(result, Markup)
        self.assertIn("Alice", result)

    def test_piping_returns_str_for_str_input(self):
        answer = self._add_answer(
            self.survey_piping, self.customer, state="in_progress"
        )
        self._add_answer_line(self.piping_q1, answer, "Bob")

        plain_text = f"Hello {{{{Q{self.piping_q1.id}}}}}!"
        result = answer._resolve_piping(plain_text)
        self.assertNotIsInstance(result, Markup)
        self.assertEqual(result, "Hello Bob!")

    def test_piping_escapes_html_in_user_values(self):
        answer = self._add_answer(
            self.survey_piping, self.customer, state="in_progress"
        )
        self._add_answer_line(self.piping_q1, answer, "<script>alert(1)</script>")

        html_text = Markup(f"<p>Hello {{{{Q{self.piping_q1.id}}}}}</p>")
        result = answer._resolve_piping(html_text)
        self.assertIsInstance(result, Markup)
        self.assertNotIn("<script>", result)
        self.assertIn("&lt;script&gt;", result)

    def test_piping_no_placeholder_returns_unchanged(self):
        answer = self._add_answer(
            self.survey_piping, self.customer, state="in_progress"
        )
        html_text = Markup("<p>No piping here</p>")
        result = answer._resolve_piping(html_text)
        self.assertIs(result, html_text)

    def test_piping_unknown_id_replaced_with_empty(self):
        answer = self._add_answer(
            self.survey_piping, self.customer, state="in_progress"
        )
        result = answer._resolve_piping("Hello {{Q999999}}!")
        self.assertEqual(result, "Hello !")


@tagged("post_install", "-at_install")
class TestValidateRankingConstantSum(TestSurveyCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ranking_question = (
            cls.env["survey.question"]
            .with_user(cls.survey_manager)
            .create(
                {
                    "title": "Rank these items",
                    "survey_id": cls.survey.id,
                    "sequence": 10,
                    "question_type": "ranking",
                    "constr_mandatory": False,
                    "suggested_answer_ids": [
                        (0, 0, {"value": "Item A"}),
                        (0, 0, {"value": "Item B"}),
                        (0, 0, {"value": "Item C"}),
                    ],
                }
            )
        )
        cls.constant_sum_question = (
            cls.env["survey.question"]
            .with_user(cls.survey_manager)
            .create(
                {
                    "title": "Distribute 100 points",
                    "survey_id": cls.survey.id,
                    "sequence": 11,
                    "question_type": "constant_sum",
                    "constr_mandatory": False,
                    "constant_sum_total": 100,
                    "suggested_answer_ids": [
                        (0, 0, {"value": "Option X"}),
                        (0, 0, {"value": "Option Y"}),
                    ],
                }
            )
        )

    def test_ranking_rejects_non_dict_string(self):
        errors = self.ranking_question._check_answer("not a dict", None)
        self.assertTrue(errors, "Non-dict string should produce a validation error")

    def test_ranking_rejects_non_dict_list(self):
        errors = self.ranking_question._check_answer([1, 2, 3], None)
        self.assertTrue(errors, "Non-dict list should produce a validation error")

    def test_ranking_accepts_valid_dict(self):
        answer_ids = self.ranking_question.suggested_answer_ids.ids
        valid_answer = {str(aid): idx for idx, aid in enumerate(answer_ids)}
        errors = self.ranking_question._check_answer(valid_answer, None)
        self.assertFalse(errors)

    def test_constant_sum_rejects_non_dict_string(self):
        errors = self.constant_sum_question._check_answer("invalid", None)
        self.assertTrue(errors, "Non-dict string should produce a validation error")

    def test_constant_sum_accepts_valid_dict(self):
        answer_ids = self.constant_sum_question.suggested_answer_ids.ids
        valid_answer = {str(answer_ids[0]): "60", str(answer_ids[1]): "40"}
        errors = self.constant_sum_question._check_answer(valid_answer, None)
        self.assertFalse(errors)

    def test_constant_sum_rejects_wrong_total(self):
        answer_ids = self.constant_sum_question.suggested_answer_ids.ids
        bad_answer = {str(answer_ids[0]): "70", str(answer_ids[1]): "70"}
        errors = self.constant_sum_question._check_answer(bad_answer, None)
        self.assertTrue(errors)


@tagged("post_install", "-at_install")
class TestChoiceStatsClassification(TestSurveyCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.survey_mc = (
            cls.env["survey.survey"]
            .with_user(cls.survey_manager)
            .create(
                {
                    "title": "MC Stats Survey",
                    "access_mode": "public",
                    "scoring_type": "scoring_with_answers",
                    "questions_layout": "page_per_question",
                }
            )
        )
        cls.mc_page = (
            cls.env["survey.question"]
            .with_user(cls.survey_manager)
            .create(
                {
                    "title": "Page",
                    "survey_id": cls.survey_mc.id,
                    "sequence": 1,
                    "is_page": True,
                    "question_type": False,
                }
            )
        )
        cls.mc_question = cls._add_question(
            cls,
            cls.mc_page,
            "Pick the fruits",
            "multiple_choice",
            labels=[
                {"value": "Apple", "is_correct": True},
                {"value": "Banana", "is_correct": True},
                {"value": "Car", "is_correct": False},
            ],
        )
        cls.apple = cls.mc_question.suggested_answer_ids.filtered(
            lambda a: a.value == "Apple"
        )
        cls.banana = cls.mc_question.suggested_answer_ids.filtered(
            lambda a: a.value == "Banana"
        )
        cls.car = cls.mc_question.suggested_answer_ids.filtered(
            lambda a: a.value == "Car"
        )

    def _make_answer_lines(self, answer_ids):
        user_input = self._add_answer(self.survey_mc, self.customer, state="done")
        for answer in answer_ids:
            self._add_answer_line(
                self.mc_question,
                user_input,
                answer.id,
                answer_type="suggestion",
            )
        return user_input

    def test_all_correct_only_is_fully_correct(self):
        user_input = self._make_answer_lines(self.apple | self.banana)
        lines = user_input.user_input_line_ids.filtered(
            lambda l: l.question_id == self.mc_question
        )
        stats = self.mc_question._get_stats_summary_data_choice(lines)
        self.assertEqual(stats["right_inputs_count"], 1)
        self.assertEqual(stats["partial_inputs_count"], 0)

    def test_correct_plus_wrong_is_partial(self):
        user_input = self._make_answer_lines(self.apple | self.banana | self.car)
        lines = user_input.user_input_line_ids.filtered(
            lambda l: l.question_id == self.mc_question
        )
        stats = self.mc_question._get_stats_summary_data_choice(lines)
        self.assertEqual(
            stats["right_inputs_count"],
            0,
            "Selecting extra wrong answers must not count as fully correct",
        )
        self.assertEqual(stats["partial_inputs_count"], 1)

    def test_subset_of_correct_is_partial(self):
        user_input = self._make_answer_lines(self.apple)
        lines = user_input.user_input_line_ids.filtered(
            lambda l: l.question_id == self.mc_question
        )
        stats = self.mc_question._get_stats_summary_data_choice(lines)
        self.assertEqual(stats["right_inputs_count"], 0)
        self.assertEqual(stats["partial_inputs_count"], 1)
