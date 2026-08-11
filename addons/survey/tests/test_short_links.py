import json

from odoo.tests import tagged
from odoo.tests.common import HttpCase

from odoo.addons.survey.tests import common


@tagged("post_install", "-at_install")
class TestSurveyShortLinks(common.TestSurveyCommon, HttpCase):
    """Resolution order of the /s/<code> short-link handler."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.form = cls.env["survey.survey"].create(
            {
                "title": "Short link survey",
                "access_mode": "public",
                "users_login_required": False,
            }
        )
        cls.env["survey.question"].create(
            {
                "title": "Anything",
                "survey_id": cls.form.id,
                "question_type": "char_box",
            }
        )

    def _open(self, code):
        return self.url_open(f"/s/{code}", allow_redirects=False)

    def test_live_session_code_redirects_to_the_survey(self):
        """An open session resolves its code straight to the survey."""
        self.form.session_state = "ready"
        response = self._open(self.form.session_code)
        self.assertEqual(response.status_code, 303)
        self.assertIn(self.form.access_token, response.headers["Location"])

    def test_custom_slug_resolves_when_no_session_matches(self):
        """A vanity slug is the second resolution step."""
        self.form.slug = "encuesta-clientes"
        response = self._open("encuesta-clientes")
        self.assertEqual(response.status_code, 303)
        self.assertIn(self.form.access_token, response.headers["Location"])

    def test_token_prefix_resolves_as_a_last_resort(self):
        """The first characters of the access token also open the survey."""
        response = self._open(self.form.access_token[:8])
        self.assertEqual(response.status_code, 303)
        self.assertIn(self.form.access_token, response.headers["Location"])

    def test_archived_survey_is_not_reachable_by_slug(self):
        """An archived survey drops out of the slug and token lookups."""
        self.form.slug = "archivada"
        self.form.action_archive()
        response = self._open("archivada")
        self.assertEqual(response.status_code, 200)
        self.assertIn("session_code", response.text)

    def test_unknown_code_renders_the_entry_page(self):
        """An unmatched code lands on the code entry page, never a 500."""
        response = self.url_open("/s/definitely-not-a-code")
        self.assertEqual(response.status_code, 200)
        self.assertIn("session_code", response.text)

    def _check_code(self, code):
        response = self.url_open(
            f"/survey/check_session_code/{code}",
            data=json.dumps(
                {"jsonrpc": "2.0", "method": "call", "params": {}, "id": 1}
            ),
            headers={"Content-Type": "application/json"},
        )
        return response.json()["result"]

    def test_check_code_returns_the_start_url_for_a_live_session(self):
        """The code checker hands the client the survey url."""
        self.form.session_state = "ready"
        result = self._check_code(self.form.session_code)
        self.assertIn(self.form.access_token, result["survey_url"])

    def test_certification_is_never_reachable_by_session_code(self):
        """A certification refuses the session-code shortcut by design."""
        self.form.write({"session_state": "ready", "certification": True})
        self.assertEqual(
            self._check_code(self.form.session_code)["error"], "survey_wrong"
        )

    def test_unlaunched_session_reports_its_own_error(self):
        """A session that was never launched is reported as such."""
        self.form.session_state = False
        self.assertEqual(
            self._check_code(self.form.session_code)["error"],
            "survey_session_not_launched",
        )

    def test_code_entry_page_renders(self):
        """The bare /s page offers the code entry form."""
        response = self.url_open("/s")
        self.assertEqual(response.status_code, 200)
        self.assertIn("session_code", response.text)
