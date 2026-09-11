from odoo.tests import TransactionCase


class TestSlideChannelEnrollOnCreate(TransactionCase):
    def test_a_course_for_attendees_only_is_enrolled_on_invitation(self):
        channel = self.env["slide.channel"].create(
            {"name": "Members only", "visibility": "members"}
        )

        self.assertEqual(channel.enroll, "invite")

    def test_a_public_course_is_open_to_enroll(self):
        channel = self.env["slide.channel"].create({"name": "Open"})

        self.assertEqual(channel.enroll, "public")

    def test_an_explicit_enroll_policy_wins(self):
        channel = self.env["slide.channel"].create(
            {"name": "Invite", "visibility": "public", "enroll": "invite"}
        )

        self.assertEqual(channel.enroll, "invite")
