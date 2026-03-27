# Part of Odoo. See LICENSE file for full copyright and licensing details.

from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests import common

from odoo.addons.mail.tests.common import mail_new_test_user


class TestMentorship(common.TransactionCase):
    """Tests for the gamification mentorship system."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        patch_email = patch(
            "odoo.addons.mail.models.mail_template.MailTemplate.send_mail",
            lambda *args, **kwargs: None,
        )
        cls.startClassPatcher(patch_email)

        cls.mentor = mail_new_test_user(
            cls.env,
            login="mentor_user",
            name="Mentor User",
            email="mentor@example.com",
            karma=500,
            groups="base.group_user",
        )
        cls.mentee = mail_new_test_user(
            cls.env,
            login="mentee_user",
            name="Mentee User",
            email="mentee@example.com",
            karma=50,
            groups="base.group_user",
        )

    def _create_mentorship(self, **kwargs):
        """Helper to create a mentorship record."""
        vals = {
            "mentor_id": self.mentor.id,
            "mentee_id": self.mentee.id,
            "mentor_karma_per_milestone": 25,
            "mentor_karma_on_completion": 100,
            **kwargs,
        }
        return self.env["gamification.mentorship"].create(vals)

    def test_create_mentorship(self):
        """Basic mentorship creation."""
        m = self._create_mentorship()
        self.assertEqual(m.state, "active")
        self.assertEqual(m.mentor_id, self.mentor)
        self.assertEqual(m.mentee_id, self.mentee)

    def test_self_mentoring_prevented(self):
        """Users cannot mentor themselves."""
        with self.assertRaises(ValidationError):
            self._create_mentorship(mentee_id=self.mentor.id)

    def test_complete_grants_karma(self):
        """Completing a mentorship grants karma to the mentor."""
        m = self._create_mentorship()
        initial_karma = self.mentor.karma

        m.action_complete()

        self.assertEqual(m.state, "completed")
        self.assertTrue(m.end_date)
        self.assertEqual(
            self.mentor.karma,
            initial_karma + m.mentor_karma_on_completion,
        )

    def test_complete_grants_badge(self):
        """Completing with a badge grants it to both parties."""
        badge = self.env["gamification.badge"].create(
            {
                "name": "Mentor Badge",
                "rule_auth": "nobody",
            }
        )
        m = self._create_mentorship(completion_badge_id=badge.id)

        m.action_complete()

        for user in (self.mentor, self.mentee):
            badge_users = self.env["gamification.badge.user"].search(
                [
                    ("user_id", "=", user.id),
                    ("badge_id", "=", badge.id),
                ]
            )
            self.assertEqual(
                len(badge_users), 1, f"{user.name} should have completion badge"
            )

    def test_cancel_mentorship(self):
        """Cancelling sets state and end_date."""
        m = self._create_mentorship()
        m.action_cancel()

        self.assertEqual(m.state, "cancelled")
        self.assertTrue(m.end_date)

    def test_on_mentee_rank_up_grants_mentor_karma(self):
        """Mentor earns karma when mentee ranks up."""
        m = self._create_mentorship()
        initial_karma = self.mentor.karma

        Mentorship = self.env["gamification.mentorship"]
        Mentorship._on_mentee_rank_up(self.mentee)

        self.assertEqual(m.mentee_milestones_reached, 1)
        self.assertEqual(
            self.mentor.karma,
            initial_karma + m.mentor_karma_per_milestone,
        )

    def test_on_mentee_rank_up_only_active(self):
        """Only active mentorships get milestone rewards."""
        m = self._create_mentorship()
        m.action_cancel()
        initial_karma = self.mentor.karma

        Mentorship = self.env["gamification.mentorship"]
        Mentorship._on_mentee_rank_up(self.mentee)

        self.assertEqual(self.mentor.karma, initial_karma)

    def test_get_suggested_mentors(self):
        """Suggested mentors are higher-karma users not already mentoring."""
        Mentorship = self.env["gamification.mentorship"]
        suggestions = Mentorship.with_user(self.mentee).get_suggested_mentors(limit=5)

        self.assertIsInstance(suggestions, list)
        # Should not include the mentee themselves
        user_ids = [s["user_id"] for s in suggestions]
        self.assertNotIn(self.mentee.id, user_ids)
        # All suggested should have higher karma
        for s in suggestions:
            self.assertGreater(s["karma"], self.mentee.karma)

    def test_display_name(self):
        """Display name shows mentor and mentee names."""
        m = self._create_mentorship()
        self.assertIn(self.mentor.name, m.display_name)
        self.assertIn(self.mentee.name, m.display_name)
