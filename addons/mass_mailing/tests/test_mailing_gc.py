from datetime import UTC, datetime

from dateutil.relativedelta import relativedelta

from odoo.tests import tagged

from odoo.addons.mass_mailing.tests.common import MassMailCommon


@tagged("mail_mail", "post_install", "-at_install")
class TestGcCanceledMailMail(MassMailCommon):
    """``mass_mailing.cancelled_mails_months_limit`` is read as an integer.

    ``get_param`` answers with the stored *string* as soon as the parameter is set, so
    ``months_limit <= 0`` raised ``TypeError: '<=' not supported between instances of
    'str' and 'int'``. The method is an ``@api.autovacuum``, so that took the whole
    vacuum down for any database that had configured the retention.
    """

    def setUp(self):
        super().setUp()
        self.icp = self.env["ir.config_parameter"].sudo()

    def _make_canceled_mail(self, months_old):
        message = self.env["mail.message"].create(
            {
                "email_from": "gc@test.example.com",
                "message_type": "email_outgoing",
                "subject": "GC",
            }
        )
        mail = self.env["mail.mail"].create(
            {
                "body_html": "<p>GC</p>",
                "email_from": "gc@test.example.com",
                "mail_message_id": message.id,
                "state": "cancel",
            }
        )
        self.env.cr.execute(
            "UPDATE mail_mail SET write_date = %s WHERE id = %s",
            [datetime.now(UTC) - relativedelta(months=months_old), mail.id],
        )
        mail.invalidate_recordset(["write_date"])
        return mail

    def test_it_runs_when_the_parameter_is_unset(self):
        self.icp.set_param("mass_mailing.cancelled_mails_months_limit", False)
        self.env["mail.mail"]._gc_canceled_mail_mail()

    def test_it_runs_when_the_parameter_is_set(self):
        self.icp.set_param("mass_mailing.cancelled_mails_months_limit", "6")
        self.env["mail.mail"]._gc_canceled_mail_mail()

    def test_a_configured_retention_is_honoured(self):
        self.icp.set_param("mass_mailing.cancelled_mails_months_limit", "6")
        old = self._make_canceled_mail(months_old=12)
        recent = self._make_canceled_mail(months_old=1)
        self.env["mail.mail"]._gc_canceled_mail_mail()
        self.assertFalse(old.exists(), "a mail past the retention was kept")
        self.assertTrue(recent.exists(), "a mail inside the retention was collected")

    def test_a_zero_or_negative_retention_disables_the_collection(self):
        for stored in ("0", "-1"):
            with self.subTest(stored=stored):
                self.icp.set_param("mass_mailing.cancelled_mails_months_limit", stored)
                old = self._make_canceled_mail(months_old=99)
                self.env["mail.mail"]._gc_canceled_mail_mail()
                self.assertTrue(
                    old.exists(), "the collection ran although it was switched off"
                )
