from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestRecruitmentTour(HttpCase):
    def test_hr_recruitment_tour(self):
        self.env["mail.alias.domain"].create(
            {"name": "recruit.example.com", "company_ids": self.env.company.ids}
        )
        Stage = self.env["hr.recruitment.stage"]
        first_stage = Stage.search(
            [("fold", "=", False)], order="sequence, id", limit=1
        )
        parked_job = self.env["hr.job"].create(
            {"name": "Parked stages", "sequence": 99}
        )
        (Stage.search([]) - first_stage).write({"job_ids": parked_job.ids})
        hired_stage = Stage.create(
            {
                "name": "Hired (tour)",
                "sequence": first_stage.sequence + 1,
                "hired_stage": True,
            }
        )
        job = self.env["hr.job"].create({"name": "Aardvark Wrangler", "sequence": 0})
        applicant = self.env["hr.applicant"].create(
            {
                "partner_name": "Tour Applicant",
                "email_from": "tour.applicant@example.com",
                "job_id": job.id,
            }
        )
        self.assertEqual(applicant.stage_id, first_stage)

        self.start_tour("/odoo", "hr_recruitment_tour", login="admin")

        self.assertEqual(applicant.stage_id, hired_stage)
        self.assertTrue(applicant.date_closed)
        self.assertTrue(applicant.employee_id)
        self.assertEqual(applicant.employee_id.job_id, job)
        created_job = self.env["hr.job"].search([("name", "=", "Test Developer")])
        self.assertEqual(created_job.alias_email, "test-developer@recruit.example.com")
