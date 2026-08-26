import json

from odoo import http
from odoo.exceptions import ValidationError
from odoo.tests import HttpCase, TransactionCase, tagged

from .common import TestSurveyCommon


class TestSurveyAuditCommon(TestSurveyCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.public_user = cls.env.ref("base.public_user")

    def _scored_survey(self, **kwargs):
        vals = {
            "title": "Audit certification",
            "access_mode": "public",
            "scoring_type": "scoring_with_answers",
            "certification": True,
            "scoring_success_min": 50.0,
            "questions_layout": "page_per_question",
            "question_and_page_ids": [
                (
                    0,
                    0,
                    {
                        "title": "Q1",
                        "sequence": 1,
                        "question_type": "simple_choice",
                        "suggested_answer_ids": [
                            (0, 0, {"value": "wrong", "answer_score": 0.0}),
                            (
                                0,
                                0,
                                {
                                    "value": "right",
                                    "answer_score": 1.0,
                                    "is_correct": True,
                                },
                            ),
                        ],
                    },
                ),
                (
                    0,
                    0,
                    {
                        "title": "Q2",
                        "sequence": 2,
                        "question_type": "simple_choice",
                        "suggested_answer_ids": [
                            (0, 0, {"value": "wrong2", "answer_score": 0.0}),
                            (
                                0,
                                0,
                                {
                                    "value": "right2",
                                    "answer_score": 99.0,
                                    "is_correct": True,
                                },
                            ),
                        ],
                    },
                ),
            ],
        }
        vals.update(kwargs)
        return self.env["survey.survey"].create(vals)


@tagged("post_install", "-at_install")
class TestAnswerOwnership(TestSurveyAuditCommon):
    def test_validator_rejects_another_questions_answer(self):
        survey = self._scored_survey()
        q1, q2 = survey.question_ids
        errors = q1._check_answer(str(q2.suggested_answer_ids[1].id))
        self.assertIn(q1.id, errors)

    def test_validator_rejects_another_surveys_answer(self):
        survey = self._scored_survey()
        other = self._scored_survey(title="Other")
        errors = survey.question_ids[0]._check_answer(
            str(other.question_ids[1].suggested_answer_ids[1].id)
        )
        self.assertIn(survey.question_ids[0].id, errors)

    def test_save_lines_refuses_a_foreign_answer(self):
        survey = self._scored_survey()
        q1, q2 = survey.question_ids
        answer = survey._create_answer(user=self.public_user)
        with self.assertRaises(ValidationError):
            answer._save_lines(q1, str(q2.suggested_answer_ids[1].id))

    def test_matrix_refuses_a_foreign_row(self):
        survey = self.env["survey.survey"].create(
            {
                "title": "Matrix",
                "access_mode": "public",
                "question_and_page_ids": [
                    (
                        0,
                        0,
                        {
                            "title": "M1",
                            "question_type": "matrix",
                            "sequence": 1,
                            "matrix_row_ids": [(0, 0, {"value": "row1"})],
                            "suggested_answer_ids": [(0, 0, {"value": "col1"})],
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "title": "M2",
                            "question_type": "matrix",
                            "sequence": 2,
                            "matrix_row_ids": [(0, 0, {"value": "other"})],
                            "suggested_answer_ids": [(0, 0, {"value": "othercol"})],
                        },
                    ),
                ],
            }
        )
        q1, q2 = survey.question_ids
        answer = survey._create_answer(user=self.public_user)
        foreign = {str(q2.matrix_row_ids[0].id): [q2.suggested_answer_ids[0].id]}
        self.assertIn(q1.id, q1._check_answer(foreign))
        with self.assertRaises(ValidationError):
            answer._save_lines(q1, foreign)

    def test_own_answers_are_still_accepted(self):
        survey = self._scored_survey()
        q1 = survey.question_ids[0]
        answer = survey._create_answer(user=self.public_user)
        self.assertEqual(q1._check_answer(str(q1.suggested_answer_ids[1].id)), {})
        answer._save_lines(q1, str(q1.suggested_answer_ids[1].id))
        self.assertEqual(answer.user_input_line_ids.answer_score, 1.0)


@tagged("post_install", "-at_install")
class TestShortLinkResolution(TestSurveyAuditCommon):
    def test_only_the_published_prefix_length_resolves(self):
        survey = self.env["survey.survey"].create(
            {
                "title": "Short",
                "access_mode": "public",
                "access_token": "cafe1234-0000-0000-0000-000000000000",
                "question_and_page_ids": [
                    (0, 0, {"title": "q", "question_type": "char_box"})
                ],
            }
        )
        length = survey.SHORT_TOKEN_LENGTH
        for shorter in range(1, length):
            self.assertFalse(
                survey._resolve_short_token(survey.access_token[:shorter]),
                f"a {shorter}-character prefix resolved to a survey",
            )
        self.assertEqual(
            survey._resolve_short_token(survey.access_token[:length]), survey
        )

    def test_token_mode_surveys_are_not_reachable_by_short_link(self):
        survey = self.env["survey.survey"].create(
            {
                "title": "Private",
                "access_mode": "token",
                "access_token": "beef1234-0000-0000-0000-000000000000",
                "question_and_page_ids": [
                    (0, 0, {"title": "q", "question_type": "char_box"})
                ],
            }
        )
        self.assertFalse(
            survey._resolve_short_token(
                survey.access_token[: survey.SHORT_TOKEN_LENGTH]
            ),
            "a short link exposed the access token of an invite-only survey",
        )

    def test_an_ambiguous_prefix_resolves_to_nothing(self):
        common = "dead12"
        for suffix in ("aa", "bb"):
            self.env["survey.survey"].create(
                {
                    "title": f"S{suffix}",
                    "access_mode": "public",
                    "access_token": f"{common}{suffix}-0000-0000-0000-000000000000",
                    "question_and_page_ids": [
                        (0, 0, {"title": "q", "question_type": "char_box"})
                    ],
                }
            )
        self.assertFalse(self.env["survey.survey"]._resolve_short_token(common))


@tagged("post_install", "-at_install")
class TestScoringPropagation(TestSurveyAuditCommon):
    def test_editing_an_answer_score_updates_stored_line_and_input(self):
        survey = self._scored_survey()
        q1 = survey.question_ids[0]
        right = q1.suggested_answer_ids[1]
        answer = survey._create_answer(user=self.public_user)
        answer._save_lines(q1, str(right.id))
        answer._mark_done()
        self.env.flush_all()

        right.answer_score = 50.0
        self.env.flush_all()
        self.env.invalidate_all()

        line = answer.user_input_line_ids.filtered(lambda ln: ln.question_id == q1)
        self.assertEqual(line.answer_score, 50.0)
        self.assertEqual(answer.scoring_total, 50.0)

    def test_flipping_is_correct_updates_stored_correctness(self):
        survey = self._scored_survey()
        q1 = survey.question_ids[0]
        wrong = q1.suggested_answer_ids[0]
        answer = survey._create_answer(user=self.public_user)
        answer._save_lines(q1, str(wrong.id))
        answer._mark_done()
        self.env.flush_all()

        wrong.write({"is_correct": True, "answer_score": 5.0})
        self.env.flush_all()
        self.env.invalidate_all()

        line = answer.user_input_line_ids.filtered(lambda ln: ln.question_id == q1)
        self.assertTrue(line.answer_is_correct)

    def test_max_obtainable_agrees_with_the_scoring_denominator(self):
        survey = self.env["survey.survey"].create(
            {
                "title": "Types",
                "access_mode": "public",
                "scoring_type": "scoring_with_answers",
                "question_and_page_ids": [
                    (
                        0,
                        0,
                        {
                            "title": "SC",
                            "sequence": 1,
                            "question_type": "simple_choice",
                            "suggested_answer_ids": [
                                (
                                    0,
                                    0,
                                    {
                                        "value": "a",
                                        "answer_score": 3.0,
                                        "is_correct": True,
                                    },
                                ),
                                (
                                    0,
                                    0,
                                    {
                                        "value": "b",
                                        "answer_score": 5.0,
                                        "is_correct": True,
                                    },
                                ),
                            ],
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "title": "MC",
                            "sequence": 2,
                            "question_type": "multiple_choice",
                            "suggested_answer_ids": [
                                (
                                    0,
                                    0,
                                    {
                                        "value": "c",
                                        "answer_score": 2.0,
                                        "is_correct": True,
                                    },
                                ),
                                (
                                    0,
                                    0,
                                    {
                                        "value": "d",
                                        "answer_score": 4.0,
                                        "is_correct": True,
                                    },
                                ),
                            ],
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "title": "NUM",
                            "sequence": 3,
                            "question_type": "numerical_box",
                            "answer_numerical_box": 42.0,
                            "answer_score": 7.0,
                        },
                    ),
                ],
            }
        )
        answer = survey._create_answer(user=self.public_user)
        self.env.flush_all()
        survey.invalidate_recordset()
        self.assertEqual(survey.scoring_max_obtainable, 18.0)
        self.assertEqual(
            answer.predefined_question_ids._get_max_obtainable_score(),
            survey.scoring_max_obtainable,
        )


@tagged("post_install", "-at_install")
class TestSurveyStatistics(TestSurveyAuditCommon):
    def test_test_entries_are_excluded(self):
        survey = self._scored_survey(scoring_success_min=80.0)
        q1, q2 = survey.question_ids
        real = survey._create_answer(user=self.public_user)
        real._save_lines(q1, str(q1.suggested_answer_ids[0].id))
        real._mark_done()
        rehearsal = survey._create_answer(
            user=self.env.ref("base.user_admin"), test_entry=True
        )
        rehearsal._save_lines(q2, str(q2.suggested_answer_ids[1].id))
        rehearsal._mark_done()
        self.env.flush_all()
        survey.invalidate_recordset()

        self.assertEqual(survey.answer_count, 1)
        self.assertEqual(survey.answer_done_count, 1)
        self.assertEqual(survey.success_count, 0)

    def test_in_progress_attempts_do_not_inflate_score_and_ratio(self):
        survey = self._scored_survey(scoring_success_min=80.0)
        _q1, q2 = survey.question_ids
        answers = [survey._create_answer(user=self.public_user) for _ in range(5)]
        for answer in answers:
            answer._save_lines(q2, str(q2.suggested_answer_ids[1].id))
        answers[0]._mark_done()
        self.env.flush_all()
        survey.invalidate_recordset()

        self.assertEqual(survey.answer_done_count, 1)
        self.assertEqual(survey.success_count, 1)
        self.assertLessEqual(survey.success_ratio, 100)
        self.assertLessEqual(survey.answer_score_avg, 100)

    def test_a_survey_with_no_completions_reports_zero(self):
        survey = self._scored_survey()
        survey._create_answer(user=self.public_user)
        self.env.flush_all()
        survey.invalidate_recordset()
        self.assertEqual(survey.answer_score_avg, 0)
        self.assertEqual(survey.success_ratio, 0)


@tagged("post_install", "-at_install")
class TestScheduledOpenClose(TestSurveyAuditCommon):
    def test_a_hand_archived_survey_stays_archived(self):
        survey = self._scored_survey(date_open="2020-01-01 00:00:00")
        survey.action_archive()
        self.env["survey.survey"]._cron_scheduled_open_close()
        survey.invalidate_recordset()
        self.assertFalse(survey.active)

    def test_a_closed_survey_is_not_reopened(self):
        survey = self._scored_survey(
            date_open="2020-01-01 00:00:00", date_close="2020-06-01 00:00:00"
        )
        self.env["survey.survey"]._cron_scheduled_open_close()
        survey.invalidate_recordset()
        self.assertFalse(survey.active)
        self.env["survey.survey"]._cron_scheduled_open_close()
        survey.invalidate_recordset()
        self.assertFalse(survey.active)

    def test_the_schedule_still_opens_a_survey_once(self):
        survey = self._scored_survey(date_open="2020-01-01 00:00:00", active=False)
        self.env["survey.survey"]._cron_scheduled_open_close()
        survey.invalidate_recordset()
        self.assertTrue(survey.active)
        self.assertTrue(survey.date_schedule_applied)

    def test_changing_the_open_date_re_arms_the_schedule(self):
        survey = self._scored_survey(date_open="2020-01-01 00:00:00")
        survey.action_archive()
        self.assertTrue(survey.date_schedule_applied)
        survey.date_open = "2021-01-01 00:00:00"
        self.assertFalse(survey.date_schedule_applied)
        self.env["survey.survey"]._cron_scheduled_open_close()
        survey.invalidate_recordset()
        self.assertTrue(survey.active)


@tagged("post_install", "-at_install")
class TestQuota(TestSurveyAuditCommon):
    def _quota_survey(self):
        survey = self.env["survey.survey"].create(
            {
                "title": "Quota",
                "access_mode": "public",
                "question_and_page_ids": [
                    (
                        0,
                        0,
                        {
                            "title": "Pick",
                            "question_type": "simple_choice",
                            "suggested_answer_ids": [
                                (0, 0, {"value": "A"}),
                                (0, 0, {"value": "B"}),
                            ],
                        },
                    )
                ],
            }
        )
        question = survey.question_ids[0]
        quota = self.env["survey.quota"].create(
            {
                "survey_id": survey.id,
                "question_id": question.id,
                "answer_id": question.suggested_answer_ids[0].id,
                "limit": 1,
            }
        )
        return survey, question, quota

    def test_the_quota_fills_before_the_survey_is_finished(self):
        survey, question, quota = self._quota_survey()
        answer = survey._create_answer(user=self.public_user)
        answer._mark_in_progress()
        answer._save_lines(question, str(question.suggested_answer_ids[0].id))
        self.env.flush_all()
        quota.invalidate_recordset()
        self.assertTrue(quota.is_full, "an in-progress answer did not hold its place")

    def test_respondents_honouring_the_check_do_not_exceed_the_limit(self):
        survey, question, quota = self._quota_survey()
        option_a = question.suggested_answer_ids[0]
        for _i in range(3):
            answer = survey._create_answer(user=self.public_user)
            answer._mark_in_progress()
            if not quota._check_quota([option_a.id]):
                answer._save_lines(question, str(option_a.id))
                answer._mark_done()
            self.env.flush_all()
        quota.invalidate_recordset()
        self.assertLessEqual(quota.current_count, quota.limit)

    def test_an_unrelated_answer_is_not_blocked(self):
        _survey, question, quota = self._quota_survey()
        option_b = question.suggested_answer_ids[1]
        self.assertFalse(quota._check_quota([option_b.id]))


@tagged("post_install", "-at_install")
class TestAnswerCreation(TestSurveyAuditCommon):
    def test_multi_survey_creation_does_not_cross_wire_lines(self):
        survey_a = self.env["survey.survey"].create(
            {
                "title": "A",
                "question_and_page_ids": [
                    (
                        0,
                        0,
                        {
                            "title": "mail A",
                            "question_type": "char_box",
                            "validation_email": True,
                            "save_as_email": True,
                        },
                    )
                ],
            }
        )
        survey_b = self.env["survey.survey"].create(
            {
                "title": "B",
                "question_and_page_ids": [
                    (
                        0,
                        0,
                        {
                            "title": "nick B",
                            "question_type": "char_box",
                            "save_as_nickname": True,
                        },
                    )
                ],
            }
        )
        answers = (survey_a | survey_b)._create_answer(email="x@example.com")
        for answer in answers:
            for line in answer.user_input_line_ids:
                self.assertEqual(line.question_id.survey_id, answer.survey_id)


@tagged("post_install", "-at_install")
class TestZeroIsAnAnswer(TestSurveyAuditCommon):
    def _question(self, question_type, **kwargs):
        survey = self.env["survey.survey"].create(
            {
                "title": question_type,
                "access_mode": "public",
                "question_and_page_ids": [
                    (
                        0,
                        0,
                        dict(
                            {
                                "title": "q",
                                "question_type": question_type,
                                "constr_mandatory": True,
                            },
                            **kwargs,
                        ),
                    )
                ],
            }
        )
        return survey.question_ids[0]

    def test_mandatory_nps_accepts_zero(self):
        self.assertEqual(self._question("nps")._check_answer(0), {})

    def test_mandatory_slider_accepts_zero(self):
        question = self._question("slider", slider_min=0, slider_max=100)
        self.assertEqual(question._check_answer(0), {})

    def test_mandatory_scale_accepts_zero(self):
        self.assertEqual(self._question("scale")._check_answer(0), {})

    def test_a_mandatory_question_still_rejects_nothing(self):
        for question_type in ("nps", "scale", "char_box"):
            question = self._question(question_type)
            self.assertTrue(
                question._check_answer(""),
                f"{question_type} accepted an empty mandatory answer",
            )

    def test_zero_is_not_an_answer_for_a_text_question(self):
        self.assertTrue(self._question("char_box")._check_answer(0))


@tagged("post_install", "-at_install")
class TestSessionCodes(TestSurveyAuditCommon):
    def test_archived_codes_are_treated_as_taken(self):
        archived = self.env["survey.survey"].create(
            {
                "title": "archived",
                "session_code": "987654",
                "question_and_page_ids": [
                    (0, 0, {"title": "q", "question_type": "char_box"})
                ],
            }
        )
        archived.action_archive()
        self.env.flush_all()
        taken = {
            row["session_code"]
            for row in self.env["survey.survey"]
            .sudo()
            .with_context(active_test=False)
            .search_read([("session_code", "!=", False)], ["session_code"])
        }
        self.assertIn("987654", taken)
        codes = self.env["survey.survey"]._generate_session_codes(
            code_count=5, excluded_codes=taken
        )
        self.assertNotIn("987654", codes)


@tagged("post_install", "-at_install")
class TestConditionalTriggerIntegrity(TestSurveyAuditCommon):
    def test_a_value_based_cycle_is_rejected(self):
        survey = self.env["survey.survey"].create(
            {
                "title": "Cycle",
                "access_mode": "public",
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
        question_a, question_b = survey.question_ids
        question_b.write(
            {
                "triggering_question_id": question_a.id,
                "triggering_operator": "gt",
                "triggering_value": "1",
            }
        )
        with self.assertRaises(ValidationError):
            question_a.write(
                {
                    "triggering_question_id": question_b.id,
                    "triggering_operator": "gt",
                    "triggering_value": "1",
                }
            )
            self.env.flush_all()

    def test_text_comparison_uses_one_collation_throughout(self):
        survey = self.env["survey.survey"].create(
            {
                "title": "Trigger",
                "access_mode": "public",
                "question_and_page_ids": [
                    (0, 0, {"title": "A", "sequence": 1, "question_type": "char_box"}),
                    (0, 0, {"title": "B", "sequence": 2, "question_type": "char_box"}),
                ],
            }
        )
        question_a, question_b = survey.question_ids
        question_b.write(
            {"triggering_question_id": question_a.id, "triggering_value": "Banana"}
        )
        answer = survey._create_answer(user=self.public_user)
        answer._save_lines(question_a, "apple")

        results = {}
        for operator in ("eq", "gt", "gte", "lt", "lte"):
            question_b.triggering_operator = operator
            results[operator] = answer._evaluate_value_trigger(question_b)
        self.assertFalse(results["eq"])
        self.assertFalse(results["gt"], "'apple' reported greater than 'Banana'")
        self.assertTrue(results["lt"])
        self.assertEqual(results["gte"], results["gt"] or results["eq"])


@tagged("post_install", "-at_install")
class TestCertificationBadge(TestSurveyAuditCommon):
    def _badged_survey(self):
        badge = self.env["gamification.badge"].create({"name": "Audit badge"})
        survey = self._scored_survey(
            users_login_required=True,
            certification_give_badge=True,
            certification_badge_id=badge.id,
        )
        return badge, survey

    def _challenge_count(self, badge):
        return (
            self.env["gamification.challenge"]
            .sudo()
            .search_count([("reward_id", "=", badge.id)])
        )

    def test_creation_wires_exactly_one_challenge(self):
        badge, _survey = self._badged_survey()
        self.assertEqual(self._challenge_count(badge), 1)

    def test_rewriting_the_flag_unchanged_is_a_no_op(self):
        badge, survey = self._badged_survey()
        survey.write({"certification_give_badge": True})
        self.env.flush_all()
        self.assertEqual(self._challenge_count(badge), 1)

    def test_toggling_the_flag_off_and_on_leaves_one_challenge(self):
        badge, survey = self._badged_survey()
        survey.write({"certification_give_badge": False})
        survey.write({"certification_give_badge": True})
        self.env.flush_all()
        self.assertEqual(self._challenge_count(badge), 1)


@tagged("post_install", "-at_install")
class TestMatrixRowLifecycle(TestSurveyAuditCommon):
    def test_deleting_a_row_does_not_orphan_answers(self):
        survey = self.env["survey.survey"].create(
            {
                "title": "Matrix",
                "access_mode": "public",
                "question_and_page_ids": [
                    (
                        0,
                        0,
                        {
                            "title": "M",
                            "question_type": "matrix",
                            "matrix_row_ids": [
                                (0, 0, {"value": "r1"}),
                                (0, 0, {"value": "r2"}),
                            ],
                            "suggested_answer_ids": [(0, 0, {"value": "c1"})],
                        },
                    )
                ],
            }
        )
        question = survey.question_ids[0]
        doomed = question.matrix_row_ids[1]
        answer = survey._create_answer(user=self.public_user)
        answer._save_lines(
            question, {str(doomed.id): [question.suggested_answer_ids[0].id]}
        )
        answer._mark_done()
        self.env.flush_all()
        doomed.unlink()
        self.env.flush_all()
        answer.invalidate_recordset()

        orphans = answer.user_input_line_ids.filtered(
            lambda ln: (
                ln.answer_type == "suggestion"
                and not ln.skipped
                and not ln.matrix_row_id
            )
        )
        self.assertFalse(orphans)

    def test_statistics_survive_a_line_naming_an_unknown_cell(self):
        survey = self.env["survey.survey"].create(
            {
                "title": "Matrix",
                "access_mode": "public",
                "question_and_page_ids": [
                    (
                        0,
                        0,
                        {
                            "title": "M",
                            "question_type": "matrix",
                            "matrix_row_ids": [(0, 0, {"value": "r1"})],
                            "suggested_answer_ids": [(0, 0, {"value": "c1"})],
                        },
                    )
                ],
            }
        )
        question = survey.question_ids[0]
        answer = survey._create_answer(user=self.public_user)
        answer._save_lines(
            question,
            {str(question.matrix_row_ids[0].id): [question.suggested_answer_ids[0].id]},
        )
        answer._mark_done()
        stray = self.env["survey.question.answer"].create(
            {"question_id": question.id, "value": "not displayed"}
        )
        line = answer.user_input_line_ids[0]
        line.invalidate_recordset()
        self.env.cr.execute(
            "UPDATE survey_user_input_line SET suggested_answer_id = %s WHERE id = %s",
            [stray.id, line.id],
        )
        self.env.invalidate_all()
        question._prepare_question_statistics(answer.user_input_line_ids)


@tagged("post_install", "-at_install")
class TestTextAnalysis(TestSurveyAuditCommon):
    def test_non_latin_answers_produce_keywords(self):
        survey = self.env["survey.survey"].create(
            {
                "title": "Analysis",
                "access_mode": "public",
                "question_and_page_ids": [
                    (0, 0, {"title": "Comments", "question_type": "text_box"})
                ],
            }
        )
        question = survey.question_ids[0]
        lines = self.env["survey.user_input.line"]
        for text in ("отличный сервис отличный", "отличный продукт"):
            answer = survey._create_answer(user=self.public_user)
            answer._save_lines(question, text)
            lines |= answer.user_input_line_ids
        analysis = question._get_text_analysis(lines)
        self.assertTrue(analysis["top_keywords"])


@tagged("post_install", "-at_install")
class TestClientQuestionTypeCoverage(TransactionCase):
    def test_every_rendered_question_type_has_a_submit_handler(self):
        import re
        from pathlib import Path

        module = Path(__file__).resolve().parent.parent
        templates = (module / "views" / "survey_templates.xml").read_text()
        form_js = (
            module / "static" / "src" / "interactions" / "survey_form.js"
        ).read_text()

        rendered = set(re.findall(r'data-question-type="(\w+)"', templates))
        body = re.search(
            r"\n    prepareSubmitValues\(formData, params\) \{\n(.*?)\n    \}\n",
            form_js,
            re.DOTALL,
        )
        self.assertIsNotNone(body, "prepareSubmitValues definition not found")
        handled = set(re.findall(r'case "(\w+)":', body.group(1)))
        self.assertTrue(handled, "parsed no submit cases at all")

        self.assertFalse(
            rendered - handled,
            f"question types rendered but never submitted: {sorted(rendered - handled)}",
        )


@tagged("post_install", "-at_install")
class TestAuditHttpRoutes(HttpCase):
    def setUp(self):
        super().setUp()
        self.public_user = self.env.ref("base.public_user")

    def test_csv_export_neutralises_formula_injection(self):
        survey = self.env["survey.survey"].create(
            {
                "title": "Export",
                "access_mode": "public",
                "question_and_page_ids": [
                    (0, 0, {"title": "Comment", "question_type": "text_box"})
                ],
            }
        )
        answer = survey._create_answer(user=self.public_user)
        answer._save_lines(survey.question_ids[0], "=cmd|'/c calc'!A1")
        answer._mark_done()
        self.env.flush_all()
        self.authenticate("admin", "admin")
        response = self.url_open(f"/survey/results/{survey.id}/export/csv")
        self.assertIn("'=cmd|", response.text, "payload was not escaped")
        self.assertNotIn(
            ",=cmd|", response.text, "an unescaped formula reached a CSV cell"
        )

    def test_save_later_is_throttled(self):
        survey = self.env["survey.survey"].create(
            {
                "title": "Later",
                "access_mode": "public",
                "question_and_page_ids": [
                    (0, 0, {"title": "q", "question_type": "char_box"})
                ],
            }
        )
        answer = survey._create_answer(email="victim@example.com")
        self.env.flush_all()
        before = self.env["mail.mail"].sudo().search_count([])
        outcomes = []
        for _i in range(5):
            response = self.url_open(
                f"/survey/save_later/{survey.access_token}/{answer.access_token}",
                data=json.dumps({"jsonrpc": "2.0", "method": "call", "params": {}}),
                headers={"Content-Type": "application/json"},
            )
            outcomes.append(response.json().get("result"))
        after = self.env["mail.mail"].sudo().search_count([])
        self.assertEqual(after - before, 1, f"5 calls produced {after - before} mails")
        self.assertTrue(outcomes[0].get("success"))
        self.assertEqual(outcomes[1].get("error"), "too_many_requests")

    def test_file_upload_round_trip(self):
        survey = self.env["survey.survey"].create(
            {
                "title": "Upload",
                "access_mode": "public",
                "questions_layout": "one_page",
                "question_and_page_ids": [
                    (
                        0,
                        0,
                        {
                            "title": "Attach",
                            "question_type": "file_upload",
                            "file_upload_types": ".txt",
                            "file_upload_max_size": 1,
                        },
                    )
                ],
            }
        )
        question = survey.question_ids[0]
        answer = survey._create_answer(user=self.public_user)
        answer._mark_in_progress()
        self.env.flush_all()
        self.authenticate(None, None)

        response = self.url_open(
            f"/survey/upload/{survey.access_token}/{answer.access_token}",
            files={"file": ("note.txt", b"hello", "text/plain")},
            data={
                "question_id": question.id,
                "csrf_token": http.Request.csrf_token(self),
            },
        )
        payload = response.json()
        self.assertIn("attachment_id", payload, f"upload refused: {payload}")

        answer._save_lines(question, payload["attachment_id"])
        line = answer.user_input_line_ids.filtered(
            lambda ln: ln.question_id == question
        )
        self.assertFalse(line.skipped)
        self.assertEqual(line.value_char_box, str(payload["attachment_id"]))

    def test_file_upload_rejects_a_disallowed_extension(self):
        survey = self.env["survey.survey"].create(
            {
                "title": "Upload2",
                "access_mode": "public",
                "question_and_page_ids": [
                    (
                        0,
                        0,
                        {
                            "title": "Attach",
                            "question_type": "file_upload",
                            "file_upload_types": ".pdf",
                            "file_upload_max_size": 1,
                        },
                    )
                ],
            }
        )
        question = survey.question_ids[0]
        answer = survey._create_answer(user=self.public_user)
        answer._mark_in_progress()
        self.env.flush_all()
        self.authenticate(None, None)
        response = self.url_open(
            f"/survey/upload/{survey.access_token}/{answer.access_token}",
            files={"file": ("payload.exe", b"MZ", "application/octet-stream")},
            data={
                "question_id": question.id,
                "csrf_token": http.Request.csrf_token(self),
            },
        )
        self.assertEqual(response.json().get("error"), "rejected")
        self.assertFalse(
            self.env["ir.attachment"]
            .sudo()
            .search_count(
                [("res_model", "=", "survey.user_input"), ("res_id", "=", answer.id)]
            ),
            "a rejected upload left its attachment behind",
        )

    def test_ranking_answer_round_trip(self):
        survey = self.env["survey.survey"].create(
            {
                "title": "Rank",
                "access_mode": "public",
                "questions_layout": "page_per_question",
                "question_and_page_ids": [
                    (
                        0,
                        0,
                        {
                            "title": "Rank these",
                            "question_type": "ranking",
                            "suggested_answer_ids": [
                                (0, 0, {"value": "alpha"}),
                                (0, 0, {"value": "beta"}),
                            ],
                        },
                    )
                ],
            }
        )
        question = survey.question_ids[0]
        answers = question.suggested_answer_ids
        answer = survey._create_answer(user=self.public_user)
        self.env.flush_all()
        self.url_open(
            f"/survey/begin/{survey.access_token}/{answer.access_token}",
            data=json.dumps({"jsonrpc": "2.0", "method": "call", "params": {}}),
            headers={"Content-Type": "application/json"},
        )
        self.url_open(
            f"/survey/submit/{survey.access_token}/{answer.access_token}",
            data=json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "call",
                    "params": {
                        "question_id": question.id,
                        str(question.id): {
                            str(answers[0].id): 1,
                            str(answers[1].id): 2,
                        },
                    },
                }
            ),
            headers={"Content-Type": "application/json"},
        )
        answer.invalidate_recordset()
        saved = answer.user_input_line_ids.filtered(
            lambda ln: ln.question_id == question
        )
        self.assertEqual(len(saved), 2)
        self.assertEqual(
            {ln.suggested_answer_id: ln.value_numerical_box for ln in saved},
            {answers[0]: 1.0, answers[1]: 2.0},
        )


@tagged("post_install", "-at_install")
class TestFollowupAndQuotaAccess(TestSurveyAuditCommon):
    def test_a_restricted_officer_cannot_reach_them(self):
        owner = self.env["res.users"].create(
            {
                "name": "Owner",
                "login": "audit_reg_owner",
                "email": "o@t.com",
                "group_ids": [(4, self.env.ref("survey.group_survey_user").id)],
            }
        )
        intruder = self.env["res.users"].create(
            {
                "name": "Intruder",
                "login": "audit_reg_intruder",
                "email": "i@t.com",
                "group_ids": [(4, self.env.ref("survey.group_survey_user").id)],
            }
        )
        survey = self.env["survey.survey"].create(
            {
                "title": "Restricted",
                "user_id": owner.id,
                "restrict_user_ids": [(6, 0, [owner.id])],
                "question_and_page_ids": [
                    (
                        0,
                        0,
                        {
                            "title": "Pick",
                            "question_type": "simple_choice",
                            "suggested_answer_ids": [(0, 0, {"value": "A"})],
                        },
                    )
                ],
            }
        )
        question = survey.question_ids[0]
        quota = self.env["survey.quota"].create(
            {
                "survey_id": survey.id,
                "question_id": question.id,
                "answer_id": question.suggested_answer_ids[0].id,
                "limit": 5,
            }
        )
        rule = self.env["survey.followup.rule"].create(
            {
                "survey_id": survey.id,
                "name": "secret",
                "mail_template_id": self.env.ref(
                    "survey.mail_template_user_input_invite"
                ).id,
            }
        )

        self.assertFalse(survey.with_user(intruder)._filtered_access("read"))
        self.assertFalse(quota.with_user(intruder)._filtered_access("read"))
        self.assertFalse(rule.with_user(intruder)._filtered_access("read"))
        self.assertTrue(quota.with_user(owner)._filtered_access("read"))
        self.assertTrue(rule.with_user(owner)._filtered_access("read"))


@tagged("post_install", "-at_install")
class TestWebhookSsrf(TestSurveyAuditCommon):
    def test_a_hostname_resolving_inward_is_refused(self):
        survey = self._scored_survey()
        for url in (
            "http://127.0.0.1/hook",
            "http://localhost/hook",
            "http://169.254.169.254/latest/meta-data/",
            "http://foo.internal/hook",
        ):
            with self.assertRaises(ValidationError, msg=f"{url} was accepted"):
                survey.webhook_url = url

    def test_the_request_does_not_follow_redirects(self):
        import inspect

        from ..models import survey_user_input

        source = inspect.getsource(survey_user_input.SurveyUser_Input._fire_webhook)
        self.assertIn("allow_redirects=False", source)
