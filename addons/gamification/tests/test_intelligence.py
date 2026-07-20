from unittest.mock import patch

from odoo import fields
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
        """Target increases when the user consistently meets or beats it."""
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

        # Create 3 past goals the user actually reached
        for i in range(3):
            self.env["gamification.goal"].create(
                {
                    "definition_id": self.goal_def.id,
                    "user_id": self.user.id,
                    "line_id": line.id,
                    "target_goal": 100,
                    "current": 105 + i,
                    "state": "reached",
                    "closed": True,
                    "end_date": f"2025-{i + 1:02d}-28",
                }
            )

        result = challenge._compute_adaptive_targets()
        key = (self.user.id, line.id)
        self.assertIn(key, result)
        self.assertGreater(result[key], 100, "Target should increase")

    def test_no_increase_when_consistently_missing_target(self):
        """A user who keeps falling just short must not get a harder target.

        Averaging 91% of target means failing every period.  Ramping the
        target for those users compounds the failure instead of helping.
        """
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
                    "current": 91,
                    "state": "failed",
                    "closed": True,
                    "end_date": f"2025-{i + 1:02d}-28",
                }
            )

        result = challenge._compute_adaptive_targets()
        adjusted = result.get((self.user.id, line.id))
        self.assertFalse(
            adjusted and adjusted > 100,
            f"User missing the target every period got a harder one: {adjusted}",
        )

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
        with patch.object(
            type(self.user),
            "_send_gamification_notification",
        ) as mock_notif:
            self.env["res.users"]._cron_engagement_nudges()
        # Smoke test: should complete without exceptions.
        # With no qualifying data, no notifications should fire.
        mock_notif.assert_not_called()

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

    def test_nudge_streak_warning(self):
        """Users with active streaks and 0 freeze days get warned."""
        streak_type = self.env["gamification.streak.type"].create(
            {
                "name": "Nudge Streak Type",
                "model_id": self.env.ref("base.model_res_partner").id,
                "date_field_id": self.env["ir.model.fields"]
                ._get("res.partner", "write_date")
                .id,
                "domain": "[]",
                "freeze_allowance": 0,
            }
        )
        streak = self.env["gamification.streak"].create(
            {
                "user_id": self.user.id,
                "streak_type_id": streak_type.id,
                "state": "active",
                "freeze_remaining": 0,
            }
        )
        # Force current_count >= 3 via SQL (readonly field)
        streak.env.cr.execute(
            "UPDATE gamification_streak SET current_count = 5 WHERE id = %s",
            [streak.id],
        )
        streak.invalidate_recordset()

        with patch.object(
            type(self.user),
            "_send_gamification_notification",
        ) as mock_notif:
            self.env["res.users"]._nudge_streak_warning()

        mock_notif.assert_called()

    def test_nudge_inactive_users(self):
        """Users inactive for 7+ days but active before get re-engaged."""
        from datetime import timedelta

        # Create a separate user with no recent karma to avoid interference
        inactive_user = mail_new_test_user(
            self.env,
            login="inactive_nudge",
            name="Inactive Nudge User",
            email="inactive_nudge@example.com",
            karma=0,
            groups="base.group_user",
        )
        # Move all existing tracking records to the past (outside 7-day window
        # but inside 30-day window)
        self.env["gamification.karma.tracking"].sudo().create(
            {
                "user_id": inactive_user.id,
                "old_value": 0,
                "new_value": 50,
                "tracking_date": fields.Datetime.now() - timedelta(days=15),
                "origin_ref": f"res.users,{inactive_user.id}",
                "reason": "Past activity",
            }
        )

        with patch.object(
            type(inactive_user),
            "_send_gamification_notification",
        ) as mock_notif:
            self.env["res.users"]._nudge_inactive_users()

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


class TestGoalFieldIndexes(common.TransactionCase):
    """Verify that frequently-filtered goal fields have database indexes."""

    def test_goal_state_is_indexed(self):
        """Goal state field must be indexed for cron and dashboard queries."""
        field = self.env["gamification.goal"]._fields["state"]
        self.assertTrue(
            field.index,
            "gamification.goal.state must have index=True — "
            "filtered by every cron, dashboard, and nudge query",
        )

    def test_goal_closed_is_indexed(self):
        """Goal closed field must be indexed for cron and nudge queries."""
        field = self.env["gamification.goal"]._fields["closed"]
        self.assertTrue(
            field.index,
            "gamification.goal.closed must have index=True — "
            "filtered by cron _update_all and nudge queries",
        )
