from datetime import date

from freezegun import freeze_time

from odoo import exceptions
from odoo.tests import HttpCase, tagged

from odoo.addons.mail.tests.common_activity import ActivityScheduleCase


@tagged("mail_activity", "-at_install", "post_install")
class TestMailActivityChatter(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.test_partner = cls.env["res.partner"].create(
            {
                "email": "test.partner@example.com",
                "name": "Test User",
            }
        )

    def test_mail_activity_date_format(self):
        with freeze_time("2024-01-01 09:00:00 AM"):
            LANG_CODE = "en_US"
            self.env = self.env(context={"lang": LANG_CODE})
            lang = self.env["res.lang"].search([("code", "=", LANG_CODE)])
            lang.date_format = "%d/%b/%y"
            lang.time_format = "%I:%M:%S %p"
            # write(), not assignment: res.users.write clears the ormcache
            # behind context_get when tz changes, and the session the tour
            # opens reads its timezone from there.
            self.env.ref("base.user_admin").write({"tz": "UTC"})

            self.start_tour(
                f"/web#id={self.test_partner.id}&model=res.partner",
                "mail_activity_date_format",
                login="admin",
            )

    def test_mail_activity_schedule_from_chatter(self):
        self.start_tour(
            f"/odoo/res.partner/{self.test_partner.id}",
            "mail_activity_schedule_from_chatter",
            login="admin",
        )


@tagged("-at_install", "post_install", "mail_activity")
class TestMailActivityIntegrity(ActivityScheduleCase):
    def test_mail_activity_type_master_data(self):
        call = self.env.ref("mail.mail_activity_data_call")
        meeting = self.env.ref("mail.mail_activity_data_meeting")
        todo = self.env.ref("mail.mail_activity_data_todo")
        upload = self.env.ref("mail.mail_activity_data_upload_document")
        warning = self.env.ref("mail.mail_activity_data_warning")
        with self.assertRaises(exceptions.UserError):
            call.write({"res_model": "res.partner"})
        with self.assertRaises(exceptions.UserError):
            meeting.write({"res_model": "res.partner"})
        with self.assertRaises(exceptions.UserError):
            todo.write({"res_model": "res.partner"})
        with self.assertRaises(exceptions.UserError):
            upload.write({"res_model": "res.partner"})
        with self.assertRaises(exceptions.UserError):
            warning.write({"res_model": "res.partner"})

        with self.assertRaises(exceptions.UserError):
            call.unlink()
        with self.assertRaises(exceptions.UserError):
            meeting.unlink()
        with self.assertRaises(exceptions.UserError):
            todo.unlink()


@tagged("-at_install", "post_install", "mail_activity")
class TestMailActivityReschedule(ActivityScheduleCase):
    """The reschedule dropdown offers today/tomorrow/next week; a custom date
    is the fourth target."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.record = cls.env["res.partner"].create({"name": "Rescheduled Partner"})
        cls.activity = cls.env["mail.activity"].create(
            {
                "activity_type_id": cls.activity_type_todo.id,
                "date_deadline": date(2026, 1, 5),
                "res_id": cls.record.id,
                "res_model_id": cls.env["ir.model"]._get_id("res.partner"),
                "summary": "Call them back",
                "user_id": cls.env.user.id,
            }
        )

    def test_an_activity_reschedules_to_a_date_the_user_picked(self):
        self.activity.action_reschedule_customdate("2026-12-24")
        self.assertEqual(self.activity.date_deadline, date(2026, 12, 24))

    def test_an_archived_activity_keeps_its_deadline(self):
        """`active` is what the today/tomorrow/nextweek siblings filter on."""
        self.activity.active = False
        self.activity.action_reschedule_customdate("2026-12-24")
        self.assertEqual(self.activity.date_deadline, date(2026, 1, 5))

    def test_the_record_reschedules_only_my_own_next_activity(self):
        other = self.env["mail.activity"].create(
            {
                "activity_type_id": self.activity_type_call.id,
                "date_deadline": date(2026, 1, 3),
                "res_id": self.record.id,
                "res_model_id": self.env["ir.model"]._get_id("res.partner"),
                "summary": "Someone else's",
                "user_id": self.user_employee.id,
            }
        )
        self.record.action_reschedule_my_next_customdate("2026-12-24")
        self.assertEqual(self.activity.date_deadline, date(2026, 12, 24))
        self.assertEqual(other.date_deadline, date(2026, 1, 3))
