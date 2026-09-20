from odoo.tests.common import HttpCase, freeze_time, tagged

from odoo.addons.mail.tests.common import mail_new_test_user
from odoo.addons.website_event.tests.common import TestEventOnlineCommon


@tagged("post_install", "-at_install")
class TestWebsiteEventTrack(TestEventOnlineCommon, HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["res.config.settings"].write(
            {
                "module_website_event_track_live": True,
            }
        )
        cls.demo_user = mail_new_test_user(
            cls.env,
            name="Demo User",
            login="demo_user",
            email="demo_user@example.com",
            groups="base.group_user",
        )
        cls.event_0.write({"is_published": True})
        cls.track = cls.env["event.track"].create(
            [
                {
                    "name": "Introduction class",
                    "event_id": cls.event_0.id,
                    "date": cls.event_0.date_begin,
                    "is_published": True,
                }
            ]
        )

    @freeze_time("2020-07-05")
    def test_email_reminder_tour(self):
        for user in [self.demo_user, self.env["res.users"]]:
            with self.subTest(user=user):
                self.start_tour(
                    f"{self.event_0.website_url}/agenda",
                    "email_reminder_tour",
                    login=user.login,
                )

                mails = (
                    self.env["mail.message"]
                    .search(
                        [
                            ("model", "=", self.track._name),
                            ("res_id", "=", self.track.id),
                            ("subject", "=", f"Add talk reminder: {self.track.name}"),
                        ]
                    )
                    .mail_ids.filtered(
                        lambda m, user=user: (
                            m.email_to == (user.email or "visitor@odoo.com")
                        )
                    )
                )
                self.assertEqual(len(mails), 1)

    def test_compute_is_one_day(self):
        track = self.env["event.track"].create(
            {
                "name": "Track Without Dates",
                "event_id": self.event_0.id,
            }
        )
        self.assertFalse(
            track.is_one_day, "Expected Is One Day to be False when no date is set."
        )
        self.assertTrue(track.name, "Track name should be correctly set.")
        self.assertTrue(track.event_id, "Track should be linked to the correct event.")

    def test_compute_track_time_data(self):
        track = self.env["event.track"].create(
            {
                "name": "Track Without Date Info",
                "event_id": self.event_0.id,
            }
        )
        self.assertFalse(track.is_track_live, "Track should not be live without date.")
        self.assertFalse(
            track.is_track_soon, "Track should not be marked as soon without date."
        )
        self.assertFalse(
            track.is_track_today, "Track should not be marked as today without date."
        )
        self.assertFalse(
            track.is_track_upcoming, "Track should not be upcoming without date."
        )
        self.assertFalse(track.is_track_done, "Track should not be done without date.")
        self.assertEqual(
            track.track_start_relative, 0, "Track start relative should be 0."
        )
        self.assertEqual(
            track.track_start_remaining, 0, "Track start remaining should be 0."
        )
