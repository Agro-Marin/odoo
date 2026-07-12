import datetime
import smtplib
from unittest import mock

from odoo.tests import TransactionCase


class MailCase(TransactionCase):
    def test_schedule_notification_parameters_roundtrip(self):
        """Record-valued notify kwargs (e.g. force_email_company) must survive the
        JSON round-trip through mail.message.schedule.

        Regression: notification_parameters used to be json.dumps(kwargs) directly,
        which raised ``TypeError: Object of type res.company is not JSON
        serializable`` whenever a scheduled notification carried a recordset.
        """
        Schedule = self.env["mail.message.schedule"]
        company = self.env.company
        kwargs = {
            "force_email_company": company,
            "force_send": True,
            "subtitles": ["hello"],
        }
        raw = Schedule._serialize_notification_parameters(kwargs)
        # the company is stored as its id, keeping the payload JSON-serializable
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
        # ... and rebuilt into the original recordset on replay
        self.assertEqual(params["force_email_company"], company)
        self.assertIs(params["force_send"], True)
        self.assertEqual(params["subtitles"], ["hello"])

    def test_scheduled_date_accepts_plain_date(self):
        """A ``datetime.date`` (not a ``datetime``) passed as ``scheduled_date``
        must be stored at midnight, without raising.

        Regression: the ``import datetime`` refactor left a call to
        ``datetime.combine`` (which only exists on ``datetime.datetime``), so any
        plain ``date`` reaching ``_parse_scheduled_datetime`` crashed with
        ``AttributeError: module 'datetime' has no attribute 'combine'``.
        """
        # create() path
        mail = self.env["mail.mail"].create(
            {"scheduled_date": datetime.date(2050, 1, 15)}
        )
        self.assertEqual(mail.scheduled_date, datetime.datetime(2050, 1, 15, 0, 0, 0))
        # write() path
        mail.write({"scheduled_date": datetime.date(2050, 2, 20)})
        self.assertEqual(mail.scheduled_date, datetime.datetime(2050, 2, 20, 0, 0, 0))

    def test_mail_send_non_connected_smtp_session(self):
        """Check to avoid SMTPServerDisconnected error while trying to
        disconnect smtp session that is not connected.

        This used to happens while trying to connect to a
        google smtp server with an expired token.

        Or here testing non recipients emails with non connected
        smtp session, we won't get SMTPServerDisconnected that would
        hide the other error that is raised earlier.
        """
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
        # if we get here SMTPServerDisconnected was not raised
        self.assertEqual(mail.state, "outgoing")
