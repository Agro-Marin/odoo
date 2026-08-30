from odoo.tests import HttpCase, tagged


@tagged("-at_install", "post_install", "recruitment")
class TestApplicantColorTour(HttpCase):
    def test_an_applicant_can_be_coloured_from_the_kanban(self):
        """The colour painted on the card must be reachable from the card."""
        # Leave a single card on the kanban: the stage columns are paginated and
        # the demo applications would push ours out of the first page.
        self.env["hr.applicant"].search([]).action_archive()
        job = self.env["hr.job"].create({"name": "Colour Tester"})
        applicant = self.env["hr.applicant"].create(
            {
                "partner_name": "Colourless Candidate",
                "email_from": "colourless.candidate@example.com",
                "job_id": job.id,
            }
        )
        self.assertTrue(
            applicant.stage_id, "Without a stage the card sits in a folded column."
        )
        self.assertEqual(applicant.color, 0)

        self.start_tour("/odoo", "hr_recruitment_applicant_color_tour", login="admin")

        self.assertEqual(
            applicant.color,
            4,
            "The kanban card menu must let a recruiter set the applicant's colour.",
        )
