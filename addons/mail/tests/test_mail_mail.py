import datetime
import smtplib
from unittest import mock

from odoo.tests import TransactionCase


class MailCase(TransactionCase):
    def test_schedule_notification_parameters_roundtrip(self):
        Schedule = self.env["mail.message.schedule"]
        company = self.env.company
        kwargs = {
            "force_email_company": company,
            "force_send": True,
            "subtitles": ["hello"],
        }
        raw = Schedule._serialize_notification_parameters(kwargs)
        self.assertIn(f'"force_email_company": {company.id}', raw)

        partner = self.env["res.partner"].create({"name": "sched"})
        message = partner.message_post(body="hi", partner_ids=partner.ids)
        schedule = Schedule.create(
            {
                "scheduled_datetime": "2050-01-01 00:00:00",
                "mail_message_id": message.id,
                "notification_parameters": raw,
            }
        )
        params = schedule._deserialize_notification_parameters()
        self.assertEqual(params["force_email_company"], company)
        self.assertIs(params["force_send"], True)
        self.assertEqual(params["subtitles"], ["hello"])

    def test_scheduled_date_accepts_plain_date(self):
        mail = self.env["mail.mail"].create(
            {"scheduled_date": datetime.date(2050, 1, 15)}
        )
        self.assertEqual(mail.scheduled_date, datetime.datetime(2050, 1, 15, 0, 0, 0))
        mail.write({"scheduled_date": datetime.date(2050, 2, 20)})
        self.assertEqual(mail.scheduled_date, datetime.datetime(2050, 2, 20, 0, 0, 0))

    def test_mail_send_non_connected_smtp_session(self):
        disconnected_smtpsession = mock.MagicMock()
        disconnected_smtpsession.quit.side_effect = smtplib.SMTPServerDisconnected
        mail = self.env["mail.mail"].create({})
        with mock.patch(
            "odoo.addons.base.models.ir_mail_server.IrMail_Server._connect__",
            return_value=disconnected_smtpsession,
        ):
            with mock.patch(
                "odoo.addons.mail.models.mail_mail._logger.info"
            ) as mock_logging_info:
                mail.send()
        disconnected_smtpsession.quit.assert_called_once()
        mock_logging_info.assert_any_call(
            "Ignoring SMTPServerDisconnected while trying to quit non open session"
        )
        self.assertEqual(mail.state, "outgoing")

    def _mail_with_link_instead_of_attach(self):
        """A mail whose single attachment is too big to travel as an attachment."""
        self.env["ir.config_parameter"].sudo().set_param(
            "base.default_max_email_size", "0.001"
        )
        attachment = self.env["ir.attachment"].create(
            {
                "name": "big.txt",
                "raw": b"x" * 4096,
                "res_model": "res.partner",
                "res_id": self.env.user.partner_id.id,
            }
        )
        return self.env["mail.mail"].create(
            {
                "body_html": "<p>ORIGINAL BODY</p>",
                "email_to": "recipient@example.com",
                "attachment_ids": [(4, attachment.id)],
            }
        )

    def test_attachment_links_come_before_the_body(self):
        mail = self._mail_with_link_instead_of_attach()
        body, attachments = mail._prepare_outgoing_attachments(mail.body_html, {})
        body = str(body)
        self.assertFalse(
            attachments, "the oversized attachment must have become a link"
        )
        self.assertIn("/web/content/", body)
        self.assertLess(
            body.index("/web/content/"),
            body.index("ORIGINAL BODY"),
            "attachment links must be prepended, not buried under the message",
        )
