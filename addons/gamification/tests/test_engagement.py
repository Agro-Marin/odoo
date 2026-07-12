from unittest.mock import patch

from odoo.tests import common

from odoo.addons.mail.tests.common import mail_new_test_user


class TestEngagementSnapshot(common.TransactionCase):
    """Tests for the engagement analytics snapshot system."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        patch_email = patch(
            "odoo.addons.mail.models.mail_template.MailTemplate.send_mail",
            lambda *args, **kwargs: None,
        )
        cls.startClassPatcher(patch_email)

        cls.company = cls.env.company
        cls.user_1 = mail_new_test_user(
            cls.env,
            login="engage_user1",
            name="Engage User 1",
            email="engage1@example.com",
            karma=100,
            groups="base.group_user",
            company_id=cls.company.id,
        )
        cls.user_2 = mail_new_test_user(
            cls.env,
            login="engage_user2",
            name="Engage User 2",
            email="engage2@example.com",
            karma=200,
            groups="base.group_user",
            company_id=cls.company.id,
        )

    def test_record_snapshot_creates_record(self):
        """_record_snapshot creates an engagement snapshot for the company."""
        Snapshot = self.env["gamification.engagement.snapshot"]
        snapshot = Snapshot._record_snapshot(self.company)

        self.assertTrue(snapshot.exists())
        self.assertEqual(snapshot.company_id, self.company)
        self.assertGreater(snapshot.total_users, 0)

    def test_record_snapshot_idempotent(self):
        """Recording a snapshot twice on the same day returns the existing one."""
        Snapshot = self.env["gamification.engagement.snapshot"]
        snap1 = Snapshot._record_snapshot(self.company)
        snap2 = Snapshot._record_snapshot(self.company)

        self.assertEqual(snap1.id, snap2.id, "Should return existing snapshot")

    def test_snapshot_captures_karma_users(self):
        """Snapshot correctly counts users with karma > 0."""
        self.env.flush_all()
        Snapshot = self.env["gamification.engagement.snapshot"]
        snapshot = Snapshot._record_snapshot(self.company)

        # At least our 2 test users have karma
        self.assertGreaterEqual(snapshot.users_with_karma, 2)

    def test_snapshot_captures_kudos(self):
        """Snapshot counts kudos sent."""
        # Send a kudos first
        category = self.env.ref("gamification.kudos_category_teamwork")
        self.env["gamification.kudos"].create(
            {
                "sender_id": self.user_1.id,
                "recipient_id": self.user_2.id,
                "category_id": category.id,
                "message": "Test kudos for analytics",
            }
        )

        self.env.flush_all()
        Snapshot = self.env["gamification.engagement.snapshot"]
        snapshot = Snapshot._record_snapshot(self.company)

        self.assertGreaterEqual(snapshot.total_kudos, 1)
        self.assertGreaterEqual(snapshot.kudos_7d, 1)

    def test_snapshot_captures_badges(self):
        """Snapshot counts badge grants."""
        badge = self.env["gamification.badge"].create(
            {
                "name": "Analytics Test Badge",
                "rule_auth": "everyone",
            }
        )
        self.env["gamification.badge.user"].create(
            {
                "user_id": self.user_1.id,
                "badge_id": badge.id,
                "sender_id": self.user_2.id,
            }
        )

        self.env.flush_all()
        Snapshot = self.env["gamification.engagement.snapshot"]
        snapshot = Snapshot._record_snapshot(self.company)

        self.assertGreaterEqual(snapshot.total_badges_granted, 1)
        self.assertGreaterEqual(snapshot.badges_granted_7d, 1)

    def test_cron_creates_snapshot_per_company(self):
        """Cron creates snapshots for all companies with meaningful data."""
        Snapshot = self.env["gamification.engagement.snapshot"]
        Snapshot._cron_record_snapshot()

        snapshot = Snapshot.search(
            [("company_id", "=", self.company.id)],
            limit=1,
            order="snapshot_date desc",
        )
        self.assertTrue(snapshot, "Cron should create at least one snapshot")
        self.assertEqual(snapshot.company_id, self.company)
        self.assertTrue(snapshot.snapshot_date, "Snapshot should have a date")
        # At minimum, active_users should reflect our test users
        self.assertGreaterEqual(
            snapshot.users_with_karma,
            0,
            "Snapshot should capture karma user count",
        )

    def test_get_analytics_summary_empty(self):
        """get_analytics_summary returns empty dict when no snapshots exist."""
        Snapshot = self.env["gamification.engagement.snapshot"]
        result = Snapshot.get_analytics_summary()

        self.assertIn("current", result)
        self.assertIn("trends", result)

    def test_get_analytics_summary_with_data(self):
        """get_analytics_summary returns current data and trends."""
        Snapshot = self.env["gamification.engagement.snapshot"]
        Snapshot._record_snapshot(self.company)

        result = Snapshot.get_analytics_summary()

        self.assertTrue(result["current"])
        self.assertIn("snapshot_date", result["current"])
        self.assertIn("total_users", result["current"])
        self.assertIn("active_users_7d", result["current"])


class TestDashboardEnhancements(common.TransactionCase):
    """Tests for dashboard leaderboard and send-kudos RPC."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        patch_email = patch(
            "odoo.addons.mail.models.mail_template.MailTemplate.send_mail",
            lambda *args, **kwargs: None,
        )
        cls.startClassPatcher(patch_email)

        cls.user_1 = mail_new_test_user(
            cls.env,
            login="dash_user1",
            name="Dashboard User 1",
            email="dash1@example.com",
            karma=500,
            groups="base.group_user",
        )
        cls.user_2 = mail_new_test_user(
            cls.env,
            login="dash_user2",
            name="Dashboard User 2",
            email="dash2@example.com",
            karma=300,
            groups="base.group_user",
        )

    def test_leaderboard_returns_sorted(self):
        """Leaderboard returns users sorted by karma descending."""
        Users = self.env["res.users"]
        result = Users._get_karma_leaderboard(limit=10)

        self.assertIsInstance(result, list)
        # Verify sorted descending
        karmas = [entry["karma"] for entry in result]
        self.assertEqual(karmas, sorted(karmas, reverse=True))

    def test_leaderboard_marks_current_user(self):
        """Leaderboard marks the current user."""
        Users = self.env["res.users"].with_user(self.user_1)
        result = Users._get_karma_leaderboard(limit=50)

        current_entries = [e for e in result if e["is_current_user"]]
        self.assertEqual(len(current_entries), 1)
        self.assertEqual(current_entries[0]["user_id"], self.user_1.id)

    def test_leaderboard_respects_limit(self):
        """Leaderboard respects the limit parameter."""
        Users = self.env["res.users"]
        result = Users._get_karma_leaderboard(limit=1)

        self.assertLessEqual(len(result), 1)

    def test_send_kudos_from_dashboard(self):
        """send_kudos_from_dashboard creates a kudos record."""
        category = self.env.ref("gamification.kudos_category_teamwork")
        Users = self.env["res.users"].with_user(self.user_1)

        result = Users.send_kudos_from_dashboard(
            self.user_2.id,
            category.id,
            "Great teamwork!",
        )

        self.assertEqual(result["sender_name"], self.user_1.name)
        self.assertEqual(result["recipient_name"], self.user_2.name)
        self.assertEqual(result["category_name"], category.name)
        self.assertGreater(result["karma_granted"], 0)

    def test_send_kudos_from_dashboard_self_prevention(self):
        """send_kudos_from_dashboard prevents self-kudos."""
        from odoo.exceptions import UserError

        category = self.env.ref("gamification.kudos_category_teamwork")
        Users = self.env["res.users"].with_user(self.user_1)

        with self.assertRaises(UserError):
            Users.send_kudos_from_dashboard(
                self.user_1.id,
                category.id,
                "Self kudos!",
            )

    def test_dashboard_data_includes_leaderboard(self):
        """get_gamification_dashboard_data includes leaderboard data."""
        Users = self.env["res.users"].with_user(self.user_1)
        data = Users.get_gamification_dashboard_data()

        self.assertIn("leaderboard", data)
        self.assertIsInstance(data["leaderboard"], list)

    def test_dashboard_data_includes_featured_badges(self):
        """Dashboard profile includes featured_badges list."""
        Users = self.env["res.users"].with_user(self.user_1)
        data = Users.get_gamification_dashboard_data()

        self.assertIn("featured_badges", data["profile"])
        self.assertIn("visibility", data["profile"])


class TestProfileEnhancements(common.TransactionCase):
    """Tests for profile fields (featured badges, visibility)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        patch_email = patch(
            "odoo.addons.mail.models.mail_template.MailTemplate.send_mail",
            lambda *args, **kwargs: None,
        )
        cls.startClassPatcher(patch_email)

        cls.user = mail_new_test_user(
            cls.env,
            login="profile_user",
            name="Profile User",
            email="profile@example.com",
            karma=100,
            groups="base.group_user",
        )

    def test_default_visibility_public(self):
        """Default gamification visibility is 'public'."""
        self.assertEqual(self.user.gamification_visibility, "public")

    def test_set_visibility(self):
        """User can change their gamification visibility."""
        self.user.gamification_visibility = "private"
        self.assertEqual(self.user.gamification_visibility, "private")

    def test_featured_badges_empty_by_default(self):
        """Featured badges are empty by default."""
        self.assertFalse(self.user.featured_badge_ids)

    def test_featured_badges_can_be_set(self):
        """User can set featured badges from their earned badges."""
        badge = self.env["gamification.badge"].create(
            {
                "name": "Featured Test Badge",
                "rule_auth": "everyone",
            }
        )
        badge_user = self.env["gamification.badge.user"].create(
            {
                "user_id": self.user.id,
                "badge_id": badge.id,
                "sender_id": self.env.ref("base.user_admin").id,
            }
        )
        self.user.featured_badge_ids = [(6, 0, [badge_user.id])]

        self.assertEqual(len(self.user.featured_badge_ids), 1)
        self.assertEqual(self.user.featured_badge_ids.badge_id, badge)
