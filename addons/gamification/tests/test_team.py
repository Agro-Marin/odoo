from unittest.mock import patch

from odoo.tests import common

from odoo.addons.mail.tests.common import mail_new_test_user


class TestTeam(common.TransactionCase):
    """Tests for gamification team model."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Patch send_mail to avoid actual email sending
        patch_email = patch(
            "odoo.addons.mail.models.mail_template.MailTemplate.send_mail",
            lambda *args, **kwargs: None,
        )
        cls.startClassPatcher(patch_email)

        cls.user_1 = mail_new_test_user(
            cls.env,
            login="team_user1",
            name="Team User 1",
            email="team1@example.com",
            karma=100,
            groups="base.group_user",
        )
        cls.user_2 = mail_new_test_user(
            cls.env,
            login="team_user2",
            name="Team User 2",
            email="team2@example.com",
            karma=200,
            groups="base.group_user",
        )
        cls.user_3 = mail_new_test_user(
            cls.env,
            login="team_user3",
            name="Team User 3",
            email="team3@example.com",
            karma=300,
            groups="base.group_user",
        )

    def test_member_count(self):
        """member_count reflects the number of team members."""
        team = self.env["gamification.team"].create(
            {
                "name": "Alpha Team",
                "member_ids": [(6, 0, [self.user_1.id, self.user_2.id])],
                "captain_id": self.user_1.id,
            }
        )
        self.assertEqual(team.member_count, 2)

        team.member_ids = [(4, self.user_3.id)]
        self.assertEqual(team.member_count, 3)

    def test_team_karma_aggregate(self):
        """team_karma is the sum of all members' karma."""
        team = self.env["gamification.team"].create(
            {
                "name": "Karma Team",
                "member_ids": [
                    (6, 0, [self.user_1.id, self.user_2.id, self.user_3.id])
                ],
            }
        )
        expected = self.user_1.karma + self.user_2.karma + self.user_3.karma
        self.assertEqual(team.team_karma, expected)

    def test_team_badges_aggregate(self):
        """team_badges counts total badge grants across all members."""
        team = self.env["gamification.team"].create(
            {
                "name": "Badge Team",
                "member_ids": [(6, 0, [self.user_1.id, self.user_2.id])],
            }
        )
        # Initially no badges
        self.assertEqual(team.team_badges, 0)

        # Grant a badge to user_1
        badge = self.env["gamification.badge"].create(
            {
                "name": "Test Badge",
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

        team.invalidate_recordset(["team_badges"])
        self.assertEqual(team.team_badges, 1)

    def test_empty_team_stats(self):
        """Empty team has zero karma and badges."""
        team = self.env["gamification.team"].create(
            {
                "name": "Empty Team",
            }
        )
        self.assertEqual(team.team_karma, 0)
        self.assertEqual(team.team_badges, 0)
        self.assertEqual(team.member_count, 0)

    def test_get_team_challenge_score_no_members(self):
        """Team with no members returns 0 score."""
        team = self.env["gamification.team"].create({"name": "Ghost Team"})
        challenge = self.env["gamification.challenge"].create(
            {
                "name": "Test Challenge",
                "period": "once",
            }
        )
        self.assertEqual(team.get_team_challenge_score(challenge), 0.0)

    def test_get_team_challenge_score_with_goals(self):
        """Team score is average completeness of members' goals."""
        team = self.env["gamification.team"].create(
            {
                "name": "Score Team",
                "member_ids": [(6, 0, [self.user_1.id, self.user_2.id])],
            }
        )

        # Create a challenge with one goal definition
        self.env["ir.model"]._get("res.partner")
        goal_def = self.env["gamification.goal.definition"].create(
            {
                "name": "Test Goal Def",
                "computation_mode": "manually",
                "condition": "higher",
            }
        )
        challenge = self.env["gamification.challenge"].create(
            {
                "name": "Team Test Challenge",
                "period": "once",
                "user_ids": [(6, 0, [self.user_1.id, self.user_2.id])],
            }
        )
        self.env["gamification.challenge.line"].create(
            {
                "challenge_id": challenge.id,
                "definition_id": goal_def.id,
                "target_goal": 100,
            }
        )

        # Start challenge to generate goals
        challenge.action_start()

        # Update goals manually
        goals = self.env["gamification.goal"].search(
            [
                ("challenge_id", "=", challenge.id),
                ("user_id", "in", [self.user_1.id, self.user_2.id]),
            ]
        )
        for goal in goals:
            if goal.user_id == self.user_1:
                goal.write({"current": 80})  # 80% complete
            else:
                goal.write({"current": 40})  # 40% complete

        score = team.get_team_challenge_score(challenge)
        # Average of 80% and 40% = 60%
        self.assertAlmostEqual(score, 60.0, places=0)

    def test_get_team_challenge_score_no_goals(self):
        """Team score is 0 when no goals exist for the challenge."""
        team = self.env["gamification.team"].create(
            {
                "name": "No Goals Team",
                "member_ids": [(6, 0, [self.user_1.id])],
            }
        )
        challenge = self.env["gamification.challenge"].create(
            {
                "name": "Empty Challenge",
                "period": "once",
            }
        )
        self.assertEqual(team.get_team_challenge_score(challenge), 0.0)
