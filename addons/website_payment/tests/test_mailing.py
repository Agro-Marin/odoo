from odoo.tests import tagged, users

from odoo.addons.mail.tests.common import MockEmail
from odoo.addons.payment.tests.common import PaymentCommon


@tagged("mail_template", "post_install", "-at_install")
class TestMailing(PaymentCommon, MockEmail):
    @users("admin")
    def test_donation_email(self):
        self.env.company.write(
            {
                "email": "companybot@company.com",
            }
        )
        tx = self._create_transaction("direct")
        with self.mock_mail_gateway():
            tx._send_donation_email(
                is_internal_notification=True,
                recipient_email=tx.partner_email,
            )
        self.assertMailMailWEmails(
            ["norbert.buyer@example.com"],
            "sent",
            email_values={
                "email_from": self.env.company.email_formatted,
            },
            fields_values={
                "email_from": self.env.company.email_formatted,
            },
        )

    @users("admin")
    def test_post_process_ignores_non_donations(self):
        """A plain done transaction does not trigger the donation mailing."""
        tx = self._create_transaction("direct", state="done")
        with self.mock_mail_gateway():
            tx._post_process()
        self.assertNotSentEmail()
