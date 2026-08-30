from odoo.tests import Form, HttpCase, tagged


@tagged("-at_install", "post_install", "recruitment")
class TestRecruitmentSurveyLink(HttpCase):
    """The interview link must die with the application it belongs to."""

    SURVEY_CLOSED = "This survey is now closed. Thank you for your interest!"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.survey = cls.env["survey.survey"].create(
            {
                "title": "Questions for the technical interview",
                "survey_type": "recruitment",
                "access_mode": "token",
            }
        )
        cls.env["survey.question"].create(
            {
                "title": "Why do you want this job?",
                "survey_id": cls.survey.id,
                "sequence": 2,
                "question_type": "text_box",
            }
        )
        cls.job = cls.env["hr.job"].create(
            {
                "name": "Technical worker",
                "survey_id": cls.survey.id,
                "description": None,
            }
        )
        cls.stage_hired = cls.env["hr.recruitment.stage"].create(
            {"name": "Hired", "sequence": 90, "hired_stage": True}
        )
        cls.refuse_reason = cls.env["hr.applicant.refuse.reason"].create(
            {"name": "Does not fit"}
        )

    def _new_applicant(self, email):
        return self.env["hr.applicant"].create(
            {
                "partner_name": "Jane Doe",
                "email_from": email,
                "job_id": self.job.id,
            }
        )

    def _send_interview(self, applicant):
        """Invite the applicant and return the url the candidate receives."""
        Form.from_action(
            self.env, applicant.action_send_survey()
        ).save().action_invite()
        answer = self.env["survey.user_input"].search(
            [
                ("survey_id", "=", self.survey.id),
                ("partner_id", "=", applicant.partner_id.id),
            ],
            order="id desc",
            limit=1,
        )
        self.assertTrue(answer, "The invitation must have created an interview answer.")
        return answer.get_start_url()

    def _interview_is_closed(self, url):
        response = self.url_open(url)
        self.assertEqual(response.status_code, 200)
        return self.SURVEY_CLOSED in response.content.decode("utf-8")

    def test_refusing_closes_the_interview_link(self):
        applicant = self._new_applicant("refused.candidate@example.com")
        url = self._send_interview(applicant)
        self.assertFalse(self._interview_is_closed(url))

        wizard = self.env["applicant.get.refuse.reason"].create(
            {
                "refuse_reason_id": self.refuse_reason.id,
                "applicant_ids": applicant.ids,
                "send_mail": False,
            }
        )
        wizard.action_refuse_reason_apply()

        self.assertTrue(
            self._interview_is_closed(url),
            "Refusing an applicant must close their interview link.",
        )

    def test_archiving_closes_the_interview_link(self):
        applicant = self._new_applicant("archived.candidate@example.com")
        url = self._send_interview(applicant)
        self.assertFalse(self._interview_is_closed(url))

        applicant.action_archive()

        self.assertTrue(
            self._interview_is_closed(url),
            "Archiving an applicant must close their interview link.",
        )

    def test_hiring_closes_the_interview_link(self):
        applicant = self._new_applicant("hired.candidate@example.com")
        url = self._send_interview(applicant)
        self.assertFalse(self._interview_is_closed(url))

        applicant.stage_id = self.stage_hired

        self.assertTrue(
            self._interview_is_closed(url),
            "Hiring an applicant must close their interview link.",
        )

    def test_deleting_closes_the_interview_link(self):
        applicant = self._new_applicant("deleted.candidate@example.com")
        url = self._send_interview(applicant)
        self.assertFalse(self._interview_is_closed(url))

        applicant.unlink()

        self.assertTrue(
            self._interview_is_closed(url),
            "Deleting an applicant must close their interview link.",
        )

    def test_an_unrelated_survey_of_the_same_contact_stays_open(self):
        """Closing an interview must not close the contact's other surveys."""
        applicant = self._new_applicant("polled.candidate@example.com")
        interview_url = self._send_interview(applicant)
        poll = self.env["survey.survey"].create(
            {"title": "Candidate experience poll", "access_mode": "token"}
        )
        self.env["survey.question"].create(
            {
                "title": "How did it go?",
                "survey_id": poll.id,
                "sequence": 2,
                "question_type": "text_box",
            }
        )
        poll_answer = poll._create_answer(partner=applicant.partner_id)
        poll_url = poll_answer.get_start_url()

        applicant.action_archive()

        self.assertTrue(self._interview_is_closed(interview_url))
        self.assertFalse(
            self._interview_is_closed(poll_url),
            "Only the job's own interview belongs to the application.",
        )
