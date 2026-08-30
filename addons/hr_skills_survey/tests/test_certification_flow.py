from datetime import date

from dateutil.relativedelta import relativedelta
from freezegun import freeze_time
from markupsafe import Markup

from odoo import Command, fields
from odoo.tests import tagged

from odoo.addons.survey.tests import common


@tagged("-at_install", "post_install", "functional")
class TestCertificationFlow(common.TestSurveyCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee_emp = cls.env["hr.employee"].create(
            {
                "user_id": cls.user_emp.id,
            }
        )
        cls.certification = cls.env["survey.survey"].create(
            {
                "access_mode": "public",
                "certification": True,
                "certification_validity_months": 3,
                "description": "<p>Description</p>",
                "questions_layout": "page_per_question",
                "scoring_success_min": 85.0,
                "scoring_type": "scoring_without_answers",
                "title": "Test Certification",
                "users_login_required": True,
            }
        )
        cls.certification_q0 = cls._add_question(
            cls,
            None,
            "Test question ...",
            "simple_choice",
            sequence=2,
            constr_mandatory=True,
            constr_error_msg="Please select an answer",
            survey_id=cls.certification.id,
            labels=[
                {"value": "Correct", "is_correct": True, "answer_score": 1.0},
                {"value": "Incorrect"},
            ],
        )

    def _create_passing_answer(self, partner, survey=None):
        """Answer the certification correctly, so that ``_mark_done`` scores it a pass."""
        survey = survey or self.certification
        question = survey.question_ids[0]
        return self.env["survey.user_input"].create(
            {
                "survey_id": survey.id,
                "partner_id": partner.id,
                "user_input_line_ids": [
                    Command.create(
                        {
                            "question_id": question.id,
                            "answer_type": "suggestion",
                            "suggested_answer_id": question.suggested_answer_ids.ids[0],
                        }
                    )
                ],
            }
        )

    @freeze_time("2024-03-20")
    def test_resume_line_creation(self):
        """Check that the resume line is correctly created upon certification completion.

        As we test the method "survey.user_input._mark_done" which is called in sudo from
        the controller, the test is executed with the admin user.
        """
        ResumeLine = self.env["hr.resume.line"]
        user_input_vals = {
            "survey_id": self.certification.id,
            "partner_id": self.user_emp.partner_id.id,
            "user_input_line_ids": [
                Command.create(
                    {
                        "question_id": self.certification_q0.id,
                        "answer_type": "suggestion",
                        "suggested_answer_id": self.certification_q0.suggested_answer_ids.ids[
                            0
                        ],
                    }
                )
            ],
        }
        self.env["survey.user_input"].create(user_input_vals)._mark_done()
        resume_line = ResumeLine.search(
            [("survey_id", "=", self.certification.id)], limit=1, order="id DESC"
        )
        self.assertEqual(resume_line.employee_id, self.employee_emp)
        self.assertEqual(resume_line.name, self.certification.title)
        self.assertEqual(resume_line.description, Markup("<p>Description</p>"))
        self.assertEqual(
            resume_line.line_type_id,
            self.env.ref("hr_skills_survey.resume_type_certification"),
        )
        self.assertEqual(resume_line.survey_id, self.certification)
        self.assertEqual(resume_line.date_start, fields.Date.today())
        self.assertEqual(
            resume_line.date_end, fields.Date.today() + relativedelta(months=3)
        )
        # When redoing the same certification, the resume line is updated
        self.certification.description = False
        for validity_months, expected_date_end in (
            (1, fields.Date.today() + relativedelta(months=1)),
            (6, fields.Date.today() + relativedelta(months=6)),
            (False, False),
        ):
            self.certification.certification_validity_months = validity_months
            self.env["survey.user_input"].create(user_input_vals)._mark_done()
            resume_line = ResumeLine.search(
                [("survey_id", "=", self.certification.id)], order="id DESC"
            )
            self.assertEqual(len(resume_line), 1)
            self.assertEqual(resume_line.date_start, fields.Date.today())
            self.assertEqual(resume_line.date_end, expected_date_end)
        self.assertEqual(resume_line.description, "")
        # Mark as done in batch 2 certifications for the same employee
        certification2 = self.certification.copy()
        self.certification.description = "Description 1"
        certification2.description = "Description 2"
        certification2.certification_validity_months = 9
        self.env["survey.user_input"].create(
            [
                user_input_vals,
                {
                    "survey_id": certification2.id,
                    "partner_id": self.user_emp.partner_id.id,
                    "user_input_line_ids": [
                        Command.create(
                            {
                                "question_id": certification2.question_ids[0].id,
                                "answer_type": "suggestion",
                                "suggested_answer_id": certification2.question_ids[
                                    0
                                ].suggested_answer_ids.ids[0],
                            }
                        )
                    ],
                },
            ]
        )._mark_done()
        cert_1_resume_line = ResumeLine.search(
            [("survey_id", "=", self.certification.id)], order="id DESC"
        )
        cert_2_resume_line = ResumeLine.search(
            [("survey_id", "=", certification2.id)], order="id DESC"
        )
        self.assertEqual(cert_1_resume_line.description, Markup("<p>Description 1</p>"))
        self.assertFalse(cert_1_resume_line.date_end)
        self.assertEqual(cert_2_resume_line.description, Markup("<p>Description 2</p>"))
        self.assertEqual(
            cert_2_resume_line.date_end, fields.Date.today() + relativedelta(months=9)
        )

    @freeze_time("2024-03-21")
    def test_resume_line_creation_employee_without_user(self):
        """An employee with no linked user still gets the certification on their CV.

        ``hr.employee.create`` gives every employee a work contact, so a
        certification can be sent to that partner through the invite wizard even
        when the employee has no user account at all.
        """
        employee = self.env["hr.employee"].create({"name": "Certified No User"})
        self.assertFalse(employee.user_id)
        self.assertTrue(employee.work_contact_id)

        self._create_passing_answer(employee.work_contact_id)._mark_done()

        resume_line = self.env["hr.resume.line"].search(
            [
                ("employee_id", "=", employee.id),
                ("survey_id", "=", self.certification.id),
            ]
        )
        self.assertEqual(len(resume_line), 1)
        self.assertEqual(resume_line.name, self.certification.title)
        self.assertEqual(
            resume_line.line_type_id,
            self.env.ref("hr_skills_survey.resume_type_certification"),
        )
        self.assertEqual(resume_line.date_start, fields.Date.today())
        self.assertEqual(
            resume_line.date_end, fields.Date.today() + relativedelta(months=3)
        )

    @freeze_time("2024-03-21")
    def test_resume_line_creation_deduplicates_same_certification(self):
        """Two passing answers marked done together leave a single CV line.

        ``survey.survey.action_end_session`` marks every answer of a live session
        done in one call, so the same participant can bring two passing answers
        for the same certification into a single ``_mark_done``.
        """
        first = self._create_passing_answer(self.user_emp.partner_id)
        second = self._create_passing_answer(self.user_emp.partner_id)

        (first | second)._mark_done()

        resume_line = self.env["hr.resume.line"].search(
            [
                ("employee_id", "=", self.employee_emp.id),
                ("survey_id", "=", self.certification.id),
            ]
        )
        self.assertEqual(len(resume_line), 1)

    @freeze_time("2024-03-21 02:00:00")
    def test_resume_line_dated_in_the_answering_user_timezone(self):
        """The CV line carries the date the employee saw, not the UTC one.

        The controller marks the answer done on a sudo of the answering user's
        environment, and ``sudo`` keeps the user, so the timezone is still
        theirs. At 02:00 UTC an employee in Mexico is on the previous day.
        """
        self.user_emp.tz = "America/Mexico_City"
        self.assertEqual(fields.Date.today(), date(2024, 3, 21))

        answer = self._create_passing_answer(self.user_emp.partner_id)
        answer.with_user(self.user_emp).sudo()._mark_done()

        resume_line = self.env["hr.resume.line"].search(
            [
                ("employee_id", "=", self.employee_emp.id),
                ("survey_id", "=", self.certification.id),
            ]
        )
        self.assertEqual(resume_line.date_start, date(2024, 3, 20))
        self.assertEqual(resume_line.date_end, date(2024, 6, 20))
