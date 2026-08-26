from datetime import timedelta

from odoo import Command, fields
from odoo.tests import HttpCase

from odoo.addons.survey.tests.common import TestSurveyCommon


class TestScoringMaxObtainable(TestSurveyCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.scored_survey = cls.env["survey.survey"].create(
            {
                "title": "Scored Survey",
                "scoring_type": "scoring_with_answers",
            }
        )
        page = cls.env["survey.question"].create(
            {
                "title": "Page 1",
                "survey_id": cls.scored_survey.id,
                "sequence": 1,
                "is_page": True,
                "question_type": False,
            }
        )
        cls.q_simple = cls._add_question(
            cls,
            page,
            "Favorite color",
            "simple_choice",
            survey_id=cls.scored_survey.id,
            labels=[
                {"value": "Red", "answer_score": 10, "is_correct": True},
                {"value": "Blue", "answer_score": 5},
                {"value": "Green", "answer_score": 0},
            ],
        )
        cls.q_multi = cls._add_question(
            cls,
            page,
            "Pick languages",
            "multiple_choice",
            survey_id=cls.scored_survey.id,
            labels=[
                {"value": "Python", "answer_score": 4, "is_correct": True},
                {"value": "Rust", "answer_score": 3, "is_correct": True},
                {"value": "COBOL", "answer_score": 0},
            ],
        )
        cls.q_num = cls._add_question(
            cls,
            page,
            "What is 2+2",
            "numerical_box",
            survey_id=cls.scored_survey.id,
            answer_numerical_box=4,
            answer_score=2,
        )

    def test_simple_choice_uses_max_not_sum(self):
        self.assertEqual(self.scored_survey.scoring_max_obtainable, 19)

    def test_single_correct_answer(self):
        survey = self.env["survey.survey"].create(
            {
                "title": "Single scored",
                "scoring_type": "scoring_with_answers",
            }
        )
        page = self.env["survey.question"].create(
            {
                "title": "P",
                "survey_id": survey.id,
                "sequence": 1,
                "is_page": True,
                "question_type": False,
            }
        )
        self._add_question(
            page,
            "Q",
            "simple_choice",
            survey_id=survey.id,
            labels=[
                {"value": "Right", "answer_score": 5, "is_correct": True},
                {"value": "Wrong", "answer_score": 0},
            ],
        )
        self.assertEqual(survey.scoring_max_obtainable, 5)

    def test_dropdown_uses_max(self):
        survey = self.env["survey.survey"].create(
            {
                "title": "Dropdown scored",
                "scoring_type": "scoring_with_answers",
            }
        )
        page = self.env["survey.question"].create(
            {
                "title": "P",
                "survey_id": survey.id,
                "sequence": 1,
                "is_page": True,
                "question_type": False,
            }
        )
        self._add_question(
            page,
            "Q",
            "dropdown",
            survey_id=survey.id,
            labels=[
                {"value": "A", "answer_score": 8, "is_correct": True},
                {"value": "B", "answer_score": 3},
                {"value": "C", "answer_score": 0},
            ],
        )
        self.assertEqual(survey.scoring_max_obtainable, 8)

    def test_matches_compute_scoring_values(self):
        survey = self.scored_survey
        answer = survey._create_answer(user=self.survey_manager, test_entry=True)
        self.env["survey.user_input.line"].create(
            [
                {
                    "user_input_id": answer.id,
                    "question_id": self.q_simple.id,
                    "answer_type": "suggestion",
                    "suggested_answer_id": self.q_simple.suggested_answer_ids[0].id,
                },
                {
                    "user_input_id": answer.id,
                    "question_id": self.q_multi.id,
                    "answer_type": "suggestion",
                    "suggested_answer_id": self.q_multi.suggested_answer_ids[0].id,
                },
                {
                    "user_input_id": answer.id,
                    "question_id": self.q_multi.id,
                    "answer_type": "suggestion",
                    "suggested_answer_id": self.q_multi.suggested_answer_ids[1].id,
                },
                {
                    "user_input_id": answer.id,
                    "question_id": self.q_num.id,
                    "answer_type": "numerical_box",
                    "value_numerical_box": 4,
                },
            ]
        )
        answer.invalidate_recordset(["scoring_percentage", "scoring_total"])
        self.assertEqual(answer.scoring_percentage, 100.0)


class TestSurveyStatistics(TestSurveyCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.scored_survey = cls.env["survey.survey"].create(
            {
                "title": "Stats Survey",
                "scoring_type": "scoring_with_answers",
                "scoring_success_min": 50.0,
            }
        )
        page = cls.env["survey.question"].create(
            {
                "title": "P",
                "survey_id": cls.scored_survey.id,
                "sequence": 1,
                "is_page": True,
                "question_type": False,
            }
        )
        cls.q = cls._add_question(
            cls,
            page,
            "Q",
            "simple_choice",
            survey_id=cls.scored_survey.id,
            labels=[
                {"value": "Correct", "answer_score": 10, "is_correct": True},
                {"value": "Wrong", "answer_score": 0},
            ],
        )

    def test_avg_score_excludes_in_progress(self):
        survey = self.scored_survey
        done_answer = self._add_answer(survey, self.customer, state="new")
        done_answer.write(
            {
                "predefined_question_ids": [Command.set(survey.question_ids.ids)],
            }
        )
        self.env["survey.user_input.line"].create(
            {
                "user_input_id": done_answer.id,
                "question_id": self.q.id,
                "answer_type": "suggestion",
                "suggested_answer_id": self.q.suggested_answer_ids[0].id,
            }
        )
        done_answer.write({"state": "done"})
        done_answer.invalidate_recordset(["scoring_percentage"])
        self.assertEqual(done_answer.scoring_percentage, 100.0)

        self._add_answer(survey, self.customer, state="in_progress")

        survey.invalidate_recordset()
        self.assertEqual(survey.answer_score_avg, 100.0)

    def test_success_ratio_excludes_in_progress(self):
        survey = self.scored_survey
        done_answer = self._add_answer(survey, self.customer, state="new")
        done_answer.write(
            {
                "predefined_question_ids": [Command.set(survey.question_ids.ids)],
            }
        )
        self.env["survey.user_input.line"].create(
            {
                "user_input_id": done_answer.id,
                "question_id": self.q.id,
                "answer_type": "suggestion",
                "suggested_answer_id": self.q.suggested_answer_ids[0].id,
            }
        )
        done_answer.write({"state": "done"})
        done_answer.invalidate_recordset(["scoring_percentage", "scoring_success"])
        self.assertTrue(done_answer.scoring_success)

        self._add_answer(survey, self.customer, state="in_progress")

        survey.invalidate_recordset()
        self.assertEqual(survey.success_ratio, 100)


class TestQuotaEnforcement(TestSurveyCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.survey_with_quota = cls.env["survey.survey"].create(
            {
                "title": "Quota Survey",
                "access_mode": "public",
                "questions_layout": "one_page",
            }
        )
        page = cls.env["survey.question"].create(
            {
                "title": "P",
                "survey_id": cls.survey_with_quota.id,
                "sequence": 1,
                "is_page": True,
                "question_type": False,
            }
        )
        cls.q_choice = cls._add_question(
            cls,
            page,
            "Pick one",
            "simple_choice",
            survey_id=cls.survey_with_quota.id,
            labels=[
                {"value": "Option A"},
                {"value": "Option B"},
            ],
            constr_mandatory=False,
        )
        cls.answer_a = cls.q_choice.suggested_answer_ids[0]
        cls.answer_b = cls.q_choice.suggested_answer_ids[1]

    def test_check_quota_returns_full(self):
        quota = self.env["survey.quota"].create(
            {
                "survey_id": self.survey_with_quota.id,
                "question_id": self.q_choice.id,
                "answer_id": self.answer_a.id,
                "limit": 1,
            }
        )
        ui = self._add_answer(self.survey_with_quota, self.customer, state="done")
        self.env["survey.user_input.line"].create(
            {
                "user_input_id": ui.id,
                "question_id": self.q_choice.id,
                "answer_type": "suggestion",
                "suggested_answer_id": self.answer_a.id,
            }
        )
        quota.invalidate_recordset(["current_count", "is_full"])
        self.assertTrue(quota.is_full)
        full = self.survey_with_quota.quota_ids._check_quota([self.answer_a.id])
        self.assertEqual(full, quota)

    def test_check_quota_allows_under_limit(self):
        self.env["survey.quota"].create(
            {
                "survey_id": self.survey_with_quota.id,
                "question_id": self.q_choice.id,
                "answer_id": self.answer_a.id,
                "limit": 10,
            }
        )
        full = self.survey_with_quota.quota_ids._check_quota([self.answer_a.id])
        self.assertFalse(full)

    def test_different_answer_not_blocked(self):
        quota = self.env["survey.quota"].create(
            {
                "survey_id": self.survey_with_quota.id,
                "question_id": self.q_choice.id,
                "answer_id": self.answer_a.id,
                "limit": 1,
            }
        )
        ui = self._add_answer(self.survey_with_quota, self.customer, state="done")
        self.env["survey.user_input.line"].create(
            {
                "user_input_id": ui.id,
                "question_id": self.q_choice.id,
                "answer_type": "suggestion",
                "suggested_answer_id": self.answer_a.id,
            }
        )
        quota.invalidate_recordset(["current_count", "is_full"])
        full = self.survey_with_quota.quota_ids._check_quota([self.answer_b.id])
        self.assertFalse(full)


class TestSkipToNavigation(TestSurveyCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.survey_skip = cls.env["survey.survey"].create(
            {
                "title": "Skip Survey",
                "access_mode": "public",
                "users_login_required": False,
                "questions_layout": "page_per_question",
            }
        )
        page = cls.env["survey.question"].create(
            {
                "title": "P",
                "survey_id": cls.survey_skip.id,
                "sequence": 1,
                "is_page": True,
                "question_type": False,
                "description": "<p>Intro</p>",
            }
        )
        cls.q1 = cls._add_question(
            cls,
            page,
            "Q1",
            "simple_choice",
            survey_id=cls.survey_skip.id,
            labels=[
                {"value": "Skip to Q3"},
                {"value": "Normal"},
            ],
            constr_mandatory=False,
        )
        cls.q2 = cls._add_question(
            cls,
            page,
            "Q2",
            "char_box",
            survey_id=cls.survey_skip.id,
            constr_mandatory=False,
        )
        cls.q3 = cls._add_question(
            cls,
            page,
            "Q3",
            "char_box",
            survey_id=cls.survey_skip.id,
            constr_mandatory=False,
        )
        cls.q4 = cls._add_question(
            cls,
            page,
            "Q4",
            "char_box",
            survey_id=cls.survey_skip.id,
            constr_mandatory=False,
        )
        cls.q1.suggested_answer_ids[0].write(
            {
                "skip_action": "skip_to",
                "skip_target_id": cls.q3.id,
            }
        )

    def test_skip_to_predecessor_computation(self):
        survey = self.survey_skip
        answer = survey._create_answer(user=self.survey_manager, test_entry=True)
        before_q3 = survey._get_next_page_or_question(answer, self.q3.id, go_back=True)
        self.assertEqual(before_q3, self.q2)

    def test_skip_to_navigates_to_correct_target(self):
        survey = self.survey_skip
        answer = survey._create_answer(user=self.survey_manager, test_entry=True)
        before_q3 = survey._get_next_page_or_question(answer, self.q3.id, go_back=True)
        next_q = survey._get_next_page_or_question(answer, before_q3.id)
        self.assertEqual(next_q, self.q3)

    def test_skip_to_first_question(self):
        survey = self.survey_skip
        answer = survey._create_answer(user=self.survey_manager, test_entry=True)
        first_q = survey.question_ids[0]
        before_first = survey._get_next_page_or_question(
            answer, first_q.id, go_back=True
        )
        next_q = survey._get_next_page_or_question(
            answer, before_first.id if before_first else 0
        )
        self.assertEqual(next_q, first_q)


class TestActionEndSession(TestSurveyCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.survey_session = cls.env["survey.survey"].create(
            {
                "title": "Session Survey",
                "survey_type": "live_session",
                "access_mode": "public",
                "questions_layout": "page_per_question",
                "scoring_type": "scoring_with_answers",
            }
        )
        cls.env["survey.question"].create(
            {
                "title": "P",
                "survey_id": cls.survey_session.id,
                "sequence": 1,
                "is_page": True,
                "question_type": False,
            }
        )
        cls.env["survey.question"].create(
            {
                "title": "Q1",
                "survey_id": cls.survey_session.id,
                "sequence": 2,
                "question_type": "simple_choice",
                "suggested_answer_ids": [
                    (0, 0, {"value": "A", "is_correct": True, "answer_score": 1}),
                    (0, 0, {"value": "B"}),
                ],
            }
        )

    def test_end_session_sets_end_datetime(self):
        survey = self.survey_session.with_user(self.survey_manager)
        survey.action_start_session()
        survey._session_open()

        session_answer = self._add_answer(
            survey,
            self.customer,
            state="in_progress",
            is_session_answer=True,
            start_datetime=fields.Datetime.now() - timedelta(minutes=5),
        )

        survey.action_end_session()
        session_answer.invalidate_recordset()
        self.assertEqual(session_answer.state, "done")
        self.assertTrue(
            session_answer.end_datetime,
            "action_end_session must set end_datetime via _mark_done()",
        )

    def test_end_session_preserves_historical(self):
        survey = self.survey_session.with_user(self.survey_manager)
        survey.action_start_session()
        survey._session_open()

        historical = self._add_answer(
            survey,
            self.customer,
            state="in_progress",
            is_session_answer=False,
        )
        survey.action_end_session()
        historical.invalidate_recordset()
        self.assertEqual(historical.state, "in_progress")
        self.assertFalse(historical.end_datetime)

    def test_end_session_with_no_inputs(self):
        survey = self.survey_session.with_user(self.survey_manager)
        survey.action_start_session()
        survey._session_open()
        survey.action_end_session()
        self.assertFalse(survey.session_state)


class TestShortUrlRouting(HttpCase):
    def test_slug_resolves_survey(self):
        survey = self.env["survey.survey"].create(
            {
                "title": "Slug Survey",
                "access_mode": "public",
                "slug": "customer-feedback",
            }
        )
        self.env["survey.question"].create(
            {
                "title": "P",
                "survey_id": survey.id,
                "sequence": 1,
                "is_page": True,
                "question_type": False,
            }
        )
        self.env["survey.question"].create(
            {
                "title": "Q",
                "survey_id": survey.id,
                "sequence": 2,
                "question_type": "char_box",
            }
        )

        response = self.url_open("/s/customer-feedback", allow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertIn(survey.access_token, response.headers.get("Location", ""))

    def test_short_token_resolves_survey(self):
        survey = self.env["survey.survey"].create(
            {
                "title": "Token Survey",
                "access_mode": "public",
            }
        )
        self.env["survey.question"].create(
            {
                "title": "P",
                "survey_id": survey.id,
                "sequence": 1,
                "is_page": True,
                "question_type": False,
            }
        )
        self.env["survey.question"].create(
            {
                "title": "Q",
                "survey_id": survey.id,
                "sequence": 2,
                "question_type": "char_box",
            }
        )

        short = survey.access_token[:6]
        response = self.url_open(f"/s/{short}", allow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertIn(survey.access_token, response.headers.get("Location", ""))

    def test_unknown_code_does_not_crash(self):
        response = self.url_open("/s/nonexistent_999", allow_redirects=False)
        self.assertIn(response.status_code, (200, 303))
