# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestHrRecruitmentSms(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.applicants = cls.env["hr.applicant"].create(
            [
                {"partner_name": "Jane Doe", "email_from": "jane@example.com"},
                {"partner_name": "John Roe", "email_from": "john@example.com"},
            ]
        )

    def test_action_send_sms_opens_mass_composer(self):
        """The applicant SMS action opens the composer in mass mode with a log."""
        action = self.applicants.action_send_sms()
        self.assertEqual(action["res_model"], "sms.composer")
        self.assertEqual(action["context"]["default_composition_mode"], "mass")
        self.assertTrue(action["context"]["default_mass_keep_log"])
        self.assertEqual(action["context"]["default_res_ids"], self.applicants.ids)

    def test_action_send_sms_scopes_to_recordset(self):
        """The composer targets exactly the applicants it was launched on."""
        one = self.applicants[0]
        action = one.action_send_sms()
        self.assertEqual(action["context"]["default_res_ids"], one.ids)
