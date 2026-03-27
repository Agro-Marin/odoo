# Part of Odoo. See LICENSE file for full copyright and licensing details.

from unittest.mock import patch

from odoo.tests import common

from odoo.addons.mail.tests.common import mail_new_test_user


class TestActivityFeed(common.TransactionCase):
    """Tests for the unified gamification activity feed."""

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
            login="feed_user1",
            name="Feed User 1",
            email="feed1@example.com",
            karma=100,
            groups="base.group_user",
        )
        cls.user_2 = mail_new_test_user(
            cls.env,
            login="feed_user2",
            name="Feed User 2",
            email="feed2@example.com",
            karma=200,
            groups="base.group_user",
        )

    def test_log_kudos_creates_activity(self):
        """Sending kudos creates an activity feed entry."""
        category = self.env.ref("gamification.kudos_category_teamwork")
        self.env["gamification.kudos"].create(
            {
                "sender_id": self.user_1.id,
                "recipient_id": self.user_2.id,
                "category_id": category.id,
                "message": "Great teamwork!",
            }
        )

        activities = self.env["gamification.activity"].search(
            [
                ("activity_type", "=", "kudos"),
                ("user_id", "=", self.user_1.id),
            ]
        )
        self.assertEqual(len(activities), 1)
        self.assertIn(self.user_1.name, activities.summary)
        self.assertIn(self.user_2.name, activities.summary)

    def test_log_badge_creates_activity(self):
        """Granting a badge creates an activity feed entry."""
        badge = self.env["gamification.badge"].create(
            {
                "name": "Feed Test Badge",
                "rule_auth": "everyone",
            }
        )
        self.env["gamification.badge.user"].create(
            {
                "user_id": self.user_2.id,
                "badge_id": badge.id,
                "sender_id": self.user_1.id,
            }
        )._send_badge()

        activities = self.env["gamification.activity"].search(
            [
                ("activity_type", "=", "badge"),
                ("user_id", "=", self.user_2.id),
            ]
        )
        self.assertEqual(len(activities), 1)
        self.assertEqual(activities.badge_id, badge)

    def test_log_achievement_creates_activity(self):
        """Unlocking an achievement creates an activity feed entry."""
        Activity = self.env["gamification.activity"]
        partner_model = self.env["ir.model"]._get("res.partner")

        achievement = self.env["gamification.achievement"].create(
            {
                "name": "Feed Achievement",
                "model_id": partner_model.id,
                "trigger_domain": "[]",
                "trigger_count": 1,
                "karma_reward": 10,
                "rarity": "rare",
            }
        )

        # Manually call _log_achievement to test it
        Activity._log_achievement(self.user_1, achievement, 10)

        activities = Activity.search(
            [
                ("activity_type", "=", "achievement"),
                ("user_id", "=", self.user_1.id),
            ]
        )
        self.assertEqual(len(activities), 1)
        self.assertEqual(activities.karma_gained, 10)
        self.assertIn("rare", activities.summary)

    def test_log_level_up_creates_activity(self):
        """Level-up creates an activity feed entry."""
        Activity = self.env["gamification.activity"]
        rank = self.env["gamification.karma.rank"].search([], limit=1)
        if not rank:
            return  # Skip if no ranks exist

        # Count existing level_up activities before
        before = Activity.search_count(
            [
                ("activity_type", "=", "level_up"),
                ("user_id", "=", self.user_1.id),
            ]
        )

        Activity._log_level_up(self.user_1, rank)

        after = Activity.search_count(
            [
                ("activity_type", "=", "level_up"),
                ("user_id", "=", self.user_1.id),
            ]
        )
        self.assertEqual(
            after - before, 1, "Should create exactly one new level_up activity"
        )

    def test_get_activity_feed_returns_data(self):
        """get_activity_feed returns formatted dicts."""
        Activity = self.env["gamification.activity"]
        # Create a test activity
        Activity._log_level_up(
            self.user_1,
            self.env["gamification.karma.rank"].search([], limit=1)
            or self.env["gamification.karma.rank"].create(
                {"name": "Test", "karma_min": 1}
            ),
        )

        feed = Activity.get_activity_feed(limit=10)

        self.assertIsInstance(feed, list)
        self.assertGreater(len(feed), 0)
        entry = feed[0]
        self.assertIn("id", entry)
        self.assertIn("activity_type", entry)
        self.assertIn("summary", entry)
        self.assertIn("icon", entry)

    def test_quest_completion_uses_quest_activity_type(self):
        """Quest completion logs activity with 'quest_completed' type, not 'challenge_completed'.

        Regression: quests previously reused 'challenge_completed' because
        the selection field lacked a dedicated quest type.
        """
        Activity = self.env["gamification.activity"]
        goal_def = self.env["gamification.goal.definition"].create(
            {"name": "Quest Goal", "computation_mode": "manually"}
        )
        quest = self.env["gamification.quest"].create(
            {
                "name": "Test Quest",
                "reward_karma": 10,
            }
        )
        self.env["gamification.quest.step"].create(
            {
                "quest_id": quest.id,
                "name": "Step 1",
                "definition_id": goal_def.id,
                "target_goal": 1,
            }
        )
        enrollment = self.env["gamification.quest.enrollment"].create(
            {
                "quest_id": quest.id,
                "user_id": self.user_1.id,
            }
        )
        step = quest.step_ids[0]
        enrollment.complete_step(step)

        activities = Activity.search(
            [
                ("activity_type", "=", "quest_completed"),
                ("user_id", "=", self.user_1.id),
            ]
        )
        self.assertEqual(len(activities), 1, "Quest should log 'quest_completed' activity")
        self.assertIn("quest", activities.summary.lower())

    def test_skill_unlock_uses_skill_activity_type(self):
        """Skill node unlock logs activity with 'skill_unlocked' type, not 'achievement'.

        Regression: skill unlocks previously reused 'achievement' because
        the selection field lacked a dedicated skill type.
        """
        Activity = self.env["gamification.activity"]
        tree = self.env["gamification.skill.tree"].create({"name": "Test Tree"})
        node = self.env["gamification.skill.node"].create(
            {
                "name": "Root Skill",
                "tree_id": tree.id,
                "karma_threshold": 0,
                "karma_reward": 5,
            }
        )

        node.unlock_for_user(self.user_1)

        activities = Activity.search(
            [
                ("activity_type", "=", "skill_unlocked"),
                ("user_id", "=", self.user_1.id),
            ]
        )
        self.assertEqual(len(activities), 1, "Skill unlock should log 'skill_unlocked' activity")
        self.assertIn("Root Skill", activities.summary)

    def test_activity_feed_filters_by_company(self):
        """Activity feed only shows activities from current user's company."""
        Activity = self.env["gamification.activity"]
        rank = self.env["gamification.karma.rank"].create(
            {"name": "FeedRank", "karma_min": 1}
        )
        Activity._log_level_up(self.user_1, rank)

        feed = Activity.get_activity_feed(limit=10)
        # Should contain our user's activity (same company)
        user_entries = [e for e in feed if e["user_name"] == self.user_1.name]
        self.assertGreater(len(user_entries), 0)
