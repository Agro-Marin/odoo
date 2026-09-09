from datetime import timedelta

from odoo import fields
from odoo.fields import Command
from odoo.tests import new_test_user, tagged
from odoo.tests.common import HttpCase
from odoo.tools import mute_logger

from odoo.addons.survey.tests import common


@tagged("post_install", "-at_install")
class TestSubmitGuards(common.TestSurveyCommon, HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.form = cls.env["survey.survey"].create(
            {
                "title": "Guarded survey",
                "access_mode": "public",
                "users_login_required": False,
            }
        )
        cls.page = cls.env["survey.question"].create(
            {
                "title": "Page one",
                "survey_id": cls.form.id,
                "is_page": True,
                "sequence": 1,
            }
        )
        cls.question = cls.env["survey.question"].create(
            {
                "title": "Say something",
                "survey_id": cls.form.id,
                "question_type": "char_box",
                "sequence": 2,
                "constr_mandatory": True,
                "constr_error_msg": "Answer required",
            }
        )

    def _answer(self):
        return self.env["survey.user_input"].create({"survey_id": self.form.id})

    def _submit(self, answer, payload):
        response = self._access_submit(self.form, answer.access_token, payload)
        return response.json().get("result")

    def _payload(self, value="hello"):
        return self._format_submission_data(self.question, value, {})

    def test_valid_submission_stores_the_answer(self):
        answer = self._answer()
        self._submit(answer, self._payload("hola"))
        line = answer.user_input_line_ids.filtered(
            lambda line: line.question_id == self.question
        )
        self.assertEqual(line.value_char_box, "hola")

    def test_missing_mandatory_answer_is_refused(self):
        answer = self._answer()
        result = self._submit(answer, self._payload(""))
        self.assertEqual(result[1]["error"], "validation")
        self.assertIn(str(self.question.id), result[1]["fields"])

    def test_finished_answer_cannot_be_submitted_again(self):
        answer = self._answer()
        answer.state = "done"
        result = self._submit(answer, self._payload())
        self.assertEqual(result[1]["error"], "unauthorized")

    def test_unknown_answer_token_is_refused(self):
        response = self._access_submit(self.form, "not-a-real-token", self._payload())
        result = response.json().get("result")
        self.assertIn("error", result[1])

    def test_submission_after_the_time_limit_is_refused(self):
        self.form.write({"is_time_limited": True, "time_limit": 1})
        answer = self._answer()
        answer.start_datetime = fields.Datetime.now() - timedelta(minutes=30)
        result = self._submit(answer, self._payload())
        self.assertEqual(result[1]["error"], "unauthorized")

    def test_submission_inside_the_grace_period_is_accepted(self):
        self.form.write({"is_time_limited": True, "time_limit": 30})
        answer = self._answer()
        answer.start_datetime = fields.Datetime.now() - timedelta(minutes=1)
        self._submit(answer, self._payload("in time"))
        line = answer.user_input_line_ids.filtered(
            lambda line: line.question_id == self.question
        )
        self.assertEqual(line.value_char_box, "in time")

    def test_time_limit_helper_ignores_untimed_surveys(self):
        from odoo.addons.survey.controllers.main import Survey

        answer = self._answer()
        self.assertFalse(Survey()._check_time_limit_exceeded(self.form, answer))


@tagged("post_install", "-at_install")
class TestLiveSessionSubmitGuards(common.TestSurveyCommon, HttpCase):
    """Revealing the answers has to close the question it revealed.

    Otherwise an attendee who sat the question out reads the correct answer off
    the host's screen, submits it, and scores like the ones who knew it.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.host = new_test_user(
            cls.env,
            login="reveal_host",
            groups="base.group_user,survey.group_survey_manager",
        )
        cls.bystander = new_test_user(
            cls.env, login="reveal_bystander", groups="base.group_user"
        )
        cls.form = cls.env["survey.survey"].create(
            {
                "title": "Live quiz",
                "access_mode": "public",
                "users_login_required": False,
                "survey_type": "live_session",
                "questions_layout": "page_per_question",
                "scoring_type": "scoring_with_answers",
            }
        )
        cls.question = cls.env["survey.question"].create(
            {
                "title": "Capital of France",
                "survey_id": cls.form.id,
                "question_type": "simple_choice",
                "sequence": 1,
                "suggested_answer_ids": [
                    Command.create(
                        {"value": "Paris", "is_correct": True, "answer_score": 3}
                    ),
                    Command.create({"value": "Lyon", "answer_score": 0}),
                ],
            }
        )
        cls.paris = cls.question.suggested_answer_ids[0]

    def _open_question(self):
        self.form.action_start_session()
        self.form.write(
            {
                "session_state": "in_progress",
                "session_question_id": self.question.id,
                "session_question_can_answer": True,
            }
        )

    def _attendee(self, test_entry=False):
        # Through the model, so the attendee carries `predefined_question_ids`
        # the way a real one joining the session would.
        return self.form._create_answer(test_entry=test_entry, is_session_answer=True)

    def _submit_paris(self, attendee):
        payload = self._format_submission_data(self.question, self.paris.id, {})
        response = self._access_submit(self.form, attendee.access_token, payload)
        self.assertEqual(response.status_code, 200)
        return response.json().get("result")

    def _host_rpc(self, route):
        response = self.url_open(
            route, json={"jsonrpc": "2.0", "method": "call", "params": {}, "id": 1}
        )
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_answer_is_accepted_while_the_question_is_open(self):
        self._open_question()
        attendee = self._attendee()
        result = self._submit_paris(attendee)
        self.assertFalse(result[1].get("error"))
        self.assertEqual(attendee.user_input_line_ids.suggested_answer_id, self.paris)

    def test_answer_is_refused_once_the_host_revealed(self):
        self._open_question()
        self.form.session_question_can_answer = False
        attendee = self._attendee()

        result = self._submit_paris(attendee)

        self.assertEqual(result[1].get("error"), "validation")
        self.assertIn(str(self.question.id), result[1]["fields"])
        self.assertFalse(
            attendee.user_input_line_ids, "nothing was stored, so nothing scores"
        )

    def test_the_host_own_test_entry_is_not_locked_out(self):
        self._open_question()
        self.form.session_question_can_answer = False
        attendee = self._attendee(test_entry=True)
        result = self._submit_paris(attendee)
        self.assertFalse(result[1].get("error"))

    def test_a_regular_survey_is_untouched_by_the_guard(self):
        self.form.write(
            {
                "session_state": False,
                "session_question_id": False,
                "session_question_can_answer": False,
            }
        )
        attendee = self.form._create_answer()
        result = self._submit_paris(attendee)
        self.assertFalse(
            result[1].get("error"), "the guard only speaks for session answers"
        )

    def test_host_route_closes_the_current_question(self):
        self._open_question()
        self.authenticate("reveal_host", "reveal_host")
        self._host_rpc(f"/survey/session/disable_answers/{self.form.access_token}")
        self.form.invalidate_recordset(["session_question_can_answer"])
        self.assertFalse(self.form.session_question_can_answer)

    def test_moving_to_the_next_question_reopens_answers(self):
        self._open_question()
        self.form.session_question_can_answer = False
        self.env["survey.question"].create(
            {
                "title": "Capital of Spain",
                "survey_id": self.form.id,
                "question_type": "simple_choice",
                "sequence": 2,
                "suggested_answer_ids": [Command.create({"value": "Madrid"})],
            }
        )
        self.authenticate("reveal_host", "reveal_host")

        self._host_rpc(f"/survey/session/next_question/{self.form.access_token}")

        self.form.invalidate_recordset(["session_question_can_answer"])
        self.assertTrue(self.form.session_question_can_answer)

    def test_a_bystander_cannot_close_the_question(self):
        self._open_question()
        self.authenticate("reveal_bystander", "reveal_bystander")
        with mute_logger("odoo.http"):
            self._host_rpc(f"/survey/session/disable_answers/{self.form.access_token}")
        self.form.invalidate_recordset(["session_question_can_answer"])
        self.assertTrue(
            self.form.session_question_can_answer,
            "only a survey user closes a live question",
        )
