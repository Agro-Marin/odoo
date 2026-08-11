import json

from odoo.fields import Command
from odoo.tests import new_test_user, tagged
from odoo.tests.common import HttpCase

from odoo.addons.survey.tests import common


@tagged("post_install", "-at_install")
class TestSessionHostRoutes(common.TestSurveyCommon, HttpCase):
    """Host-side session routes and the guard they share."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.host = new_test_user(
            cls.env,
            login="session_host",
            groups="base.group_user,survey.group_survey_manager",
        )
        cls.form = cls.env["survey.survey"].create(
            {
                "title": "Live session",
                "access_mode": "public",
                "users_login_required": False,
                "questions_layout": "page_per_question",
            }
        )
        cls.question = cls.env["survey.question"].create(
            {
                "title": "Pick one",
                "survey_id": cls.form.id,
                "question_type": "simple_choice",
                "suggested_answer_ids": [
                    Command.create({"value": "A"}),
                    Command.create({"value": "B"}),
                ],
            }
        )

    def _rpc(self, route):
        response = self.url_open(
            route,
            data=json.dumps(
                {"jsonrpc": "2.0", "method": "call", "params": {}, "id": 1}
            ),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(response.status_code, 200)
        return response.json().get("result")

    def _open_session(self):
        self.form.action_start_session()
        self.form.write(
            {
                "session_state": "in_progress",
                "session_question_id": self.question.id,
            }
        )

    # --- next question ---------------------------------------------------

    def test_next_question_advances_a_ready_session(self):
        """From a ready session the host route serves the first question."""
        self.form.action_start_session()
        self.authenticate("session_host", "session_host")
        result = self._rpc(f"/survey/session/next_question/{self.form.access_token}")
        self.assertTrue(result)
        self.form.invalidate_recordset(["session_state"])
        self.assertEqual(self.form.session_state, "in_progress")

    def test_next_question_without_a_session_returns_nothing(self):
        """With no session open the host route yields an empty payload."""
        self.authenticate("session_host", "session_host")
        result = self._rpc(f"/survey/session/next_question/{self.form.access_token}")
        self.assertFalse(result)

    # --- results ---------------------------------------------------------

    def test_results_are_served_for_a_live_session(self):
        """A running session returns the current question's result values."""
        self._open_session()
        self.authenticate("session_host", "session_host")
        result = self._rpc(f"/survey/session/results/{self.form.access_token}")
        self.assertIsInstance(result, dict)
        self.assertTrue(result)

    def test_results_are_refused_without_a_live_session(self):
        """A closed session serves no results at all."""
        self.authenticate("session_host", "session_host")
        result = self._rpc(f"/survey/session/results/{self.form.access_token}")
        self.assertFalse(result)

    # --- leaderboard -----------------------------------------------------

    def _attendee(self, score=5):
        answer = self.env["survey.user_input"].create(
            {
                "survey_id": self.form.id,
                "nickname": "Ana",
                "is_session_answer": True,
                "state": "in_progress",
            }
        )
        self.env["survey.user_input.line"].create(
            {
                "user_input_id": answer.id,
                "question_id": self.question.id,
                "answer_type": "suggestion",
                "suggested_answer_id": self.question.suggested_answer_ids[0].id,
                "answer_score": score,
                "skipped": False,
            }
        )
        return answer

    def test_leaderboard_renders_the_ranked_attendees(self):
        """With attendees the leaderboard comes back as rendered markup."""
        self._open_session()
        self._attendee()
        self.authenticate("session_host", "session_host")
        result = self._rpc(f"/survey/session/leaderboard/{self.form.access_token}")
        self.assertIsInstance(result, str)
        self.assertIn("Ana", result)

    def test_leaderboard_is_empty_without_attendees(self):
        """A live session with nobody scoring yet renders nothing."""
        self._open_session()
        self.authenticate("session_host", "session_host")
        self.assertEqual(
            self._rpc(f"/survey/session/leaderboard/{self.form.access_token}"),
            "",
        )

    def test_leaderboard_is_empty_without_a_live_session(self):
        """No open session means no leaderboard markup (boundary)."""
        self.authenticate("session_host", "session_host")
        result = self._rpc(f"/survey/session/leaderboard/{self.form.access_token}")
        self.assertEqual(result, "")

    def test_unknown_token_yields_no_session_data(self):
        """A token matching no survey never leaks session data."""
        self.authenticate("session_host", "session_host")
        self.assertFalse(self._rpc("/survey/session/results/not-a-token"))
        self.assertEqual(self._rpc("/survey/session/leaderboard/not-a-token"), "")
