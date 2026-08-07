from odoo.tests import HttpCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestSurveyStartRoutes(HttpCase):
    """Access gates of the public survey start flow."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.survey = cls.env['survey.survey'].create({
            'title': 'Route survey',
            'access_mode': 'public',
            'users_login_required': False,
        })
        cls.env['survey.question'].create({
            'title': 'Say something',
            'survey_id': cls.survey.id,
            'question_type': 'text_box',
        })

    def _answers(self):
        return self.env['survey.user_input'].search(
            [('survey_id', '=', self.survey.id)],
        )

    def test_start_public_survey_creates_answer(self):
        """A public visitor starting the survey gets an answer record."""
        before = len(self._answers())
        res = self.url_open(f'/survey/start/{self.survey.access_token}')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(self._answers()), before + 1)

    def test_start_archived_survey_creates_nothing(self):
        """An archived survey never spawns answers from the public route."""
        self.survey.action_archive()
        res = self.url_open(f'/survey/start/{self.survey.access_token}')
        self.assertEqual(res.status_code, 200)
        self.assertFalse(self._answers())
        self.assertNotIn('Say something', res.text)

    def test_start_with_unknown_token_creates_nothing(self):
        """A garbage survey token yields an error page, no crash, no data."""
        res = self.url_open('/survey/start/not-a-real-survey-token')
        self.assertEqual(res.status_code, 200)
        self.assertFalse(self._answers())

    def test_manager_test_entry_redirects_to_start(self):
        """The manager's test drive creates a test answer and redirects."""
        new_test_user(
            self.env, login='survey_mgr_routes',
            groups='base.group_user,survey.group_survey_manager',
        )
        self.authenticate('survey_mgr_routes', 'survey_mgr_routes')
        res = self.url_open(f'/survey/test/{self.survey.access_token}')
        self.assertEqual(res.status_code, 200)
        # the test drive lands straight on the survey page for the new answer
        self.assertIn(f'/survey/{self.survey.access_token}/', res.url)
        test_answers = self._answers().filtered('test_entry')
        self.assertTrue(test_answers)
