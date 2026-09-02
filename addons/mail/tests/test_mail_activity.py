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
class TestMailActivityTypeOnchange(ActivityScheduleCase):
    """Switching the activity type must not undo choices the user already made.

    The type only carries *defaults*; a type that declares none has nothing to
    say about the field, so what the user typed stands.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.test_record = cls.env["res.partner"].create({"name": "Activity Target"})
        # `activity_type_call` is the one ActivityScheduleCase leaves without a
        # default assignee, which is the case the user hits.
        cls.assertFalse(cls, cls.activity_type_call.default_user_id)
        cls.activity_type_todo.default_user_id = cls.user_admin

    def _new_activity(self, activity_type):
        return self.env["mail.activity"].new(
            {
                "res_model_id": self.env["ir.model"]._get_id("res.partner"),
                "res_id": self.test_record.id,
                "activity_type_id": activity_type.id,
            }
        )

    def test_switching_type_keeps_the_chosen_assignee(self):
        activity = self._new_activity(self.activity_type_todo)
        activity.user_id = self.user_employee
        activity.activity_type_id = self.activity_type_call
        activity._onchange_activity_type_id()
        self.assertEqual(
            activity.user_id,
            self.user_employee,
            "a type without a default assignee has no opinion on who is assigned",
        )

    def test_a_type_with_a_default_assignee_still_wins(self):
        activity = self._new_activity(self.activity_type_call)
        activity.user_id = self.user_employee
        activity.activity_type_id = self.activity_type_todo
        activity._onchange_activity_type_id()
        self.assertEqual(activity.user_id, self.user_admin)

    def test_an_unassigned_activity_still_falls_back_to_the_current_user(self):
        activity = self._new_activity(self.activity_type_call)
        activity.user_id = False
        activity._onchange_activity_type_id()
        self.assertEqual(activity.user_id, self.env.user)
