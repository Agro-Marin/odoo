# Part of Odoo. See LICENSE file for full copyright and licensing details.

from unittest.mock import patch

from odoo.tests import common

from odoo.addons.mail.tests.common import mail_new_test_user


class TestAdaptiveDifficulty(common.TransactionCase):
    """Tests for adaptive difficulty in challenges."""

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
            login="adapt_user",
            name="Adapt User",
            email="adapt@example.com",
            karma=100,
            groups="base.group_user",
        )
        cls.goal_def = cls.env["gamification.goal.definition"].create(
            {
                "name": "Adaptive Test Def",
                "computation_mode": "manually",
                "condition": "higher",
            }
        )

    def test_no_adjustment_for_once_period(self):
        """Non-recurring challenges should not be adjusted."""
        challenge = self.env["gamification.challenge"].create(
            {
                "name": "Once Challenge",
                "period": "once",
                "user_ids": [(6, 0, [self.user.id])],
            }
        )
        self.env["gamification.challenge.line"].create(
            {
                "challenge_id": challenge.id,
                "definition_id": self.goal_def.id,
                "target_goal": 100,
            }
        )
        result = challenge._compute_adaptive_targets()
        self.assertEqual(result, {})

    def test_no_adjustment_without_history(self):
        """No adjustment when user has less than 2 completed periods."""
        challenge = self.env["gamification.challenge"].create(
            {
                "name": "Monthly Challenge",
                "period": "monthly",
                "user_ids": [(6, 0, [self.user.id])],
            }
        )
        line = self.env["gamification.challenge.line"].create(
            {
                "challenge_id": challenge.id,
                "definition_id": self.goal_def.id,
                "target_goal": 100,
            }
        )

        # Create only 1 past goal (need 2+)
        self.env["gamification.goal"].create(
            {
                "definition_id": self.goal_def.id,
                "user_id": self.user.id,
                "line_id": line.id,
                "target_goal": 100,
                "current": 95,
                "state": "reached",
                "closed": True,
            }
        )

        result = challenge._compute_adaptive_targets()
        self.assertEqual(result, {})

    def test_increase_on_consistent_overperformance(self):
        """Target increases when user consistently exceeds 90%."""
        challenge = self.env["gamification.challenge"].create(
            {
                "name": "Monthly Challenge",
                "period": "monthly",
                "user_ids": [(6, 0, [self.user.id])],
            }
        )
        line = self.env["gamification.challenge.line"].create(
            {
                "challenge_id": challenge.id,
                "definition_id": self.goal_def.id,
                "target_goal": 100,
            }
        )

        # Create 3 past goals with >90% completion
        for i in range(3):
            self.env["gamification.goal"].create(
                {
                    "definition_id": self.goal_def.id,
                    "user_id": self.user.id,
                    "line_id": line.id,
                    "target_goal": 100,
                    "current": 95 + i,
                    "state": "reached",
                    "closed": True,
                    "end_date": f"2025-{i + 1:02d}-28",
                }
            )

        result = challenge._compute_adaptive_targets()
        key = (self.user.id, line.id)
        self.assertIn(key, result)
        self.assertGreater(result[key], 100, "Target should increase")

    def test_decrease_on_consistent_underperformance(self):
        """Target decreases when user consistently below 50%."""
        challenge = self.env["gamification.challenge"].create(
            {
                "name": "Monthly Challenge",
                "period": "monthly",
                "user_ids": [(6, 0, [self.user.id])],
            }
        )
        line = self.env["gamification.challenge.line"].create(
            {
                "challenge_id": challenge.id,
                "definition_id": self.goal_def.id,
                "target_goal": 100,
            }
        )

        for i in range(3):
            self.env["gamification.goal"].create(
                {
                    "definition_id": self.goal_def.id,
                    "user_id": self.user.id,
                    "line_id": line.id,
                    "target_goal": 100,
                    "current": 30 + i,
                    "state": "failed",
                    "closed": True,
                    "end_date": f"2025-{i + 1:02d}-28",
                }
            )

        result = challenge._compute_adaptive_targets()
        key = (self.user.id, line.id)
        self.assertIn(key, result)
        self.assertLess(result[key], 100, "Target should decrease")


class TestEngagementNudges(common.TransactionCase):
    """Tests for the engagement nudge system."""

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
            login="nudge_user",
            name="Nudge User",
            email="nudge@example.com",
            karma=100,
            groups="base.group_user",
        )

    def test_nudge_cron_runs_without_error(self):
        """The nudge cron runs without crashing even with no data."""
        # Should not raise
        self.env["res.users"]._cron_engagement_nudges()

    def test_nudge_close_to_rank(self):
        """Users close to next rank get notified."""
        rank = self.env["gamification.karma.rank"].create(
            {
                "name": "Close Rank",
                "karma_min": 105,
            }
        )
        self.user.next_rank_id = rank

        with patch.object(
            type(self.user),
            "_send_gamification_notification",
        ) as mock_notif:
            self.env["res.users"]._nudge_close_to_rank()

        # User has 100 karma, rank requires 105 → 5 away (within 10%)
        mock_notif.assert_called()

    def test_nudge_goals_almost_done(self):
        """Users with >80% complete goals get notified."""
        goal_def = self.env["gamification.goal.definition"].create(
            {
                "name": "Nudge Goal Def",
                "computation_mode": "manually",
            }
        )
        self.env["gamification.goal"].create(
            {
                "definition_id": goal_def.id,
                "user_id": self.user.id,
                "target_goal": 100,
                "current": 85,
                "state": "inprogress",
            }
        )

        with patch.object(
            type(self.user),
            "_send_gamification_notification",
        ) as mock_notif:
            self.env["res.users"]._nudge_goals_almost_done()

        mock_notif.assert_called()


class TestVisibilityControls(common.TransactionCase):
    """Tests for opt-out visibility in feeds and leaderboards."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        patch_email = patch(
            "odoo.addons.mail.models.mail_template.MailTemplate.send_mail",
            lambda *args, **kwargs: None,
        )
        cls.startClassPatcher(patch_email)

        cls.public_user = mail_new_test_user(
            cls.env,
            login="vis_public",
            name="Public User",
            email="public@example.com",
            karma=500,
            groups="base.group_user",
        )
        cls.private_user = mail_new_test_user(
            cls.env,
            login="vis_private",
            name="Private User",
            email="private@example.com",
            karma=1000,
            groups="base.group_user",
        )
        cls.private_user.gamification_visibility = "private"

    def test_leaderboard_excludes_private_users(self):
        """Private users do not appear in the karma leaderboard."""
        Users = self.env["res.users"]
        leaderboard = Users._get_karma_leaderboard(limit=50)

        user_ids = [e["user_id"] for e in leaderboard]
        self.assertNotIn(
            self.private_user.id,
            user_ids,
            "Private user should not appear in leaderboard",
        )

    def test_activity_feed_excludes_private_users(self):
        """Activities from private users are hidden in the feed."""
        Activity = self.env["gamification.activity"]
        rank = self.env["gamification.karma.rank"].create(
            {
                "name": "Vis Rank",
                "karma_min": 1,
            }
        )
        Activity._log_level_up(self.private_user, rank)
        Activity._log_level_up(self.public_user, rank)

        feed = Activity.get_activity_feed(limit=50)
        feed_user_names = [e["user_name"] for e in feed]

        self.assertNotIn(
            self.private_user.name,
            feed_user_names,
            "Private user's activities should be hidden",
        )
        self.assertIn(
            self.public_user.name,
            feed_user_names,
            "Public user's activities should be visible",
        )

    def test_public_user_visible_everywhere(self):
        """Public users appear in both leaderboard and feed."""
        Users = self.env["res.users"]
        leaderboard = Users._get_karma_leaderboard(limit=50)
        user_ids = [e["user_id"] for e in leaderboard]
        self.assertIn(self.public_user.id, user_ids)
