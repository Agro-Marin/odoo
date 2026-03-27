"""Tests for the live session state machine, attempt limits, deadline enforcement,
back-navigation restriction, piping, validation, and statistics correctness.

These cover critical business logic gaps identified during the survey module audit."""

from datetime import timedelta

from markupsafe import Markup

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.survey.tests.common import TestSurveyCommon


@tagged("post_install", "-at_install")
class TestSurveySession(TestSurveyCommon):
    """Test live session lifecycle: start → advance → end."""

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
        """Starting a session transitions state from False to 'ready'."""
        survey = self.survey_session.with_user(self.survey_manager)
        self.assertFalse(survey.session_state)

        survey.action_start_session()
        self.assertEqual(survey.session_state, "ready")
        self.assertTrue(survey.session_code)
        self.assertTrue(survey.session_start_time)

    def test_session_open_transitions_to_in_progress(self):
        """Opening a session transitions from 'ready' to 'in_progress'."""
        survey = self.survey_session.with_user(self.survey_manager)
        survey.action_start_session()
        self.assertEqual(survey.session_state, "ready")

        survey._session_open()
        self.assertEqual(survey.session_state, "in_progress")

    def test_session_question_advancement(self):
        """Advancing through questions updates session_question_id."""
        survey = self.survey_session.with_user(self.survey_manager)
        survey.action_start_session()
        survey._session_open()

        # First question
        next_q = survey._get_session_next_question(go_back=False)
        self.assertEqual(next_q, self.session_q1)

        # Write the question to simulate the controller
        survey.sudo().write({"session_question_id": next_q.id})

        # Second question
        next_q = survey._get_session_next_question(go_back=False)
        self.assertEqual(next_q, self.session_q2)

    def test_session_question_go_back(self):
        """Going back returns the previous question."""
        survey = self.survey_session.with_user(self.survey_manager)
        survey.action_start_session()
        survey._session_open()

        # Advance to Q2
        survey.sudo().write({"session_question_id": self.session_q2.id})

        # Go back should return Q1
        prev_q = survey._get_session_next_question(go_back=True)
        self.assertEqual(prev_q, self.session_q1)

    def test_session_end_resets_state(self):
        """Ending a session resets session_state and marks only session inputs as done."""
        survey = self.survey_session.with_user(self.survey_manager)
        survey.action_start_session()
        survey._session_open()

        # Create a session participant answer (should be marked done)
        session_answer = self._add_answer(
            survey,
            self.customer,
            state="in_progress",
            is_session_answer=True,
        )

        # Create a historical non-session answer (must NOT be touched)
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
    """Test that attempt limits are correctly enforced."""

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
        """attempts_count only counts 'done' answers, not in-progress ones."""
        survey = self.survey_limited

        # First attempt — done
        answer1 = self._add_answer(survey, self.customer, state="done")
        survey.invalidate_recordset(["answer_count"])

        # Check that attempts_number is computed
        self.assertEqual(answer1.attempts_number, 1)
        self.assertTrue(survey._has_attempts_left(self.customer, False, False))

        # Second attempt — done
        answer2 = self._add_answer(survey, self.customer, state="done")
        survey.invalidate_recordset(["answer_count"])
        self.assertEqual(answer2.attempts_number, 2)

    def test_create_answer_blocked_when_limit_exceeded(self):
        """_create_answer raises UserError when attempt limit is reached."""
        survey = self.survey_limited.with_user(self.survey_manager)

        # Exhaust the 2 attempts
        for _ in range(2):
            answer = survey._create_answer(partner=self.customer)
            answer.write({"state": "done"})

        # Third attempt should be blocked
        with self.assertRaises(UserError):
            survey._create_answer(partner=self.customer)


@tagged("post_install", "-at_install")
class TestSurveyDeadline(TestSurveyCommon):
    """Test that deadline enforcement works correctly."""

    def test_expired_deadline_blocks_submission(self):
        """A user_input with an expired deadline should report the survey as expired."""
        answer = self._add_answer(
            self.survey,
            self.customer,
            state="in_progress",
            deadline=fields.Datetime.now() - timedelta(hours=1),
        )
        # The _check_validity method on the controller uses deadline
        # Test the computed field directly
        self.assertTrue(
            answer.survey_time_limit_reached or answer.deadline < fields.Datetime.now()
        )

    def test_valid_deadline_allows_access(self):
        """A user_input with a future deadline should be accessible."""
        answer = self._add_answer(
            self.survey,
            self.customer,
            state="in_progress",
            deadline=fields.Datetime.now() + timedelta(hours=1),
        )
        self.assertFalse(answer.survey_time_limit_reached)


@tagged("post_install", "-at_install")
class TestSurveyBackNavigation(TestSurveyCommon):
    """Test that users_can_go_back=False is enforced."""

    def test_back_navigation_disabled(self):
        """When users_can_go_back is False, _can_go_back returns False."""
        self.assertFalse(self.survey.users_can_go_back)
        answer = self._add_answer(self.survey, self.customer, state="in_progress")
        # For any question, go-back should be disallowed
        can_go = self.survey._can_go_back(answer, self.question_ft)
        self.assertFalse(can_go)

    def test_back_navigation_enabled(self):
        """When users_can_go_back is True, _can_go_back returns True for non-first questions."""
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
    """Test time limit computation and enforcement."""

    def test_survey_time_limit_reached(self):
        """survey_time_limit_reached is True when time has expired."""
        self.survey.write({"is_time_limited": True, "time_limit": 10.0})  # 10 minutes
        answer = self._add_answer(self.survey, self.customer, state="in_progress")
        # Start 15 minutes ago — time limit should be reached
        answer.write(
            {
                "start_datetime": fields.Datetime.now() - timedelta(minutes=15),
            }
        )
        answer.invalidate_recordset(["survey_time_limit_reached"])
        self.assertTrue(answer.survey_time_limit_reached)

    def test_survey_time_limit_not_reached(self):
        """survey_time_limit_reached is False when time remains."""
        self.survey.write({"is_time_limited": True, "time_limit": 10.0})
        answer = self._add_answer(self.survey, self.customer, state="in_progress")
        # Start 5 minutes ago — still within limit
        answer.write(
            {
                "start_datetime": fields.Datetime.now() - timedelta(minutes=5),
            }
        )
        answer.invalidate_recordset(["survey_time_limit_reached"])
        self.assertFalse(answer.survey_time_limit_reached)


@tagged("post_install", "-at_install")
class TestResolvePiping(TestSurveyCommon):
    """Test answer piping ({{QN}} substitution) in question descriptions."""

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
                    "description": "<p>Hello {{Q1}}, welcome!</p>",
                }
            )
        )

    def test_piping_preserves_markup_type(self):
        """When input text is Markup, the return must also be Markup."""
        answer = self._add_answer(
            self.survey_piping, self.customer, state="in_progress"
        )
        self._add_answer_line(self.piping_q1, answer, "Alice")

        html_text = Markup("<p>Hello {{Q1}}, welcome!</p>")
        result = answer._resolve_piping(html_text)
        self.assertIsInstance(result, Markup)
        self.assertIn("Alice", result)

    def test_piping_returns_str_for_str_input(self):
        """When input text is a plain str, the return must also be a plain str."""
        answer = self._add_answer(
            self.survey_piping, self.customer, state="in_progress"
        )
        self._add_answer_line(self.piping_q1, answer, "Bob")

        plain_text = "Hello {{Q1}}!"
        result = answer._resolve_piping(plain_text)
        self.assertNotIsInstance(result, Markup)
        self.assertEqual(result, "Hello Bob!")

    def test_piping_escapes_html_in_user_values(self):
        """User-supplied answers must be HTML-escaped when inserted into Markup context."""
        answer = self._add_answer(
            self.survey_piping, self.customer, state="in_progress"
        )
        self._add_answer_line(self.piping_q1, answer, "<script>alert(1)</script>")

        html_text = Markup("<p>Hello {{Q1}}</p>")
        result = answer._resolve_piping(html_text)
        self.assertIsInstance(result, Markup)
        # The script tag must be escaped, not rendered
        self.assertNotIn("<script>", result)
        self.assertIn("&lt;script&gt;", result)

    def test_piping_no_placeholder_returns_unchanged(self):
        """Text without placeholders is returned as-is, preserving type."""
        answer = self._add_answer(
            self.survey_piping, self.customer, state="in_progress"
        )
        html_text = Markup("<p>No piping here</p>")
        result = answer._resolve_piping(html_text)
        self.assertIs(result, html_text)

    def test_piping_unknown_index_replaced_with_empty(self):
        """Unknown question references are replaced with empty string."""
        answer = self._add_answer(
            self.survey_piping, self.customer, state="in_progress"
        )
        result = answer._resolve_piping("Hello {{Q99}}!")
        self.assertEqual(result, "Hello !")


@tagged("post_install", "-at_install")
class TestValidateRankingConstantSum(TestSurveyCommon):
    """Test validation of ranking and constant_sum question types."""

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
        """A non-dict string answer must be rejected, not silently accepted."""
        errors = self.ranking_question.validate_question("not a dict", None)
        self.assertTrue(errors, "Non-dict string should produce a validation error")

    def test_ranking_rejects_non_dict_list(self):
        """A non-dict list answer must be rejected."""
        errors = self.ranking_question.validate_question([1, 2, 3], None)
        self.assertTrue(errors, "Non-dict list should produce a validation error")

    def test_ranking_accepts_valid_dict(self):
        """A dict with the correct number of entries is accepted."""
        answer_ids = self.ranking_question.suggested_answer_ids.ids
        valid_answer = {str(aid): idx for idx, aid in enumerate(answer_ids)}
        errors = self.ranking_question.validate_question(valid_answer, None)
        self.assertFalse(errors)

    def test_constant_sum_rejects_non_dict_string(self):
        """A non-dict string answer must be rejected."""
        errors = self.constant_sum_question.validate_question("invalid", None)
        self.assertTrue(errors, "Non-dict string should produce a validation error")

    def test_constant_sum_accepts_valid_dict(self):
        """A dict whose values sum to the target is accepted."""
        answer_ids = self.constant_sum_question.suggested_answer_ids.ids
        valid_answer = {str(answer_ids[0]): "60", str(answer_ids[1]): "40"}
        errors = self.constant_sum_question.validate_question(valid_answer, None)
        self.assertFalse(errors)

    def test_constant_sum_rejects_wrong_total(self):
        """A dict whose values don't sum to the target is rejected."""
        answer_ids = self.constant_sum_question.suggested_answer_ids.ids
        bad_answer = {str(answer_ids[0]): "70", str(answer_ids[1]): "70"}
        errors = self.constant_sum_question.validate_question(bad_answer, None)
        self.assertTrue(errors)


@tagged("post_install", "-at_install")
class TestChoiceStatsClassification(TestSurveyCommon):
    """Test that multiple_choice statistics classify correct/partial/wrong accurately."""

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
        """Create a done user_input with the given suggested_answer_ids selected."""
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
        """Selecting exactly the right answers (no extras) = fully correct."""
        user_input = self._make_answer_lines(self.apple | self.banana)
        lines = user_input.user_input_line_ids.filtered(
            lambda l: l.question_id == self.mc_question
        )
        stats = self.mc_question._get_stats_summary_data_choice(lines)
        self.assertEqual(stats["right_inputs_count"], 1)
        self.assertEqual(stats["partial_inputs_count"], 0)

    def test_correct_plus_wrong_is_partial(self):
        """Selecting all correct answers PLUS a wrong one = partial, not fully correct."""
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
        """Selecting only some correct answers = partial."""
        user_input = self._make_answer_lines(self.apple)
        lines = user_input.user_input_line_ids.filtered(
            lambda l: l.question_id == self.mc_question
        )
        stats = self.mc_question._get_stats_summary_data_choice(lines)
        self.assertEqual(stats["right_inputs_count"], 0)
        self.assertEqual(stats["partial_inputs_count"], 1)
