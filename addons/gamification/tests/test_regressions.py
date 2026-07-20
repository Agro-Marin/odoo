"""Regression tests for defects found in the gamification audit.

Each test here failed before its corresponding fix and passes after it.
Where the defect was a security one, the test also asserts the control path
(the route that was always correctly blocked) so a future refactor that
loosens the guard is caught rather than silently accepted.
"""

from datetime import date, timedelta

from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import common


class TestKarmaIntegrity(common.TransactionCase):
    """karma == sum of every recorded gain, under all insertion orders."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Tracking = cls.env["gamification.karma.tracking"]

    def _user(self, login):
        return (
            self.env["res.users"]
            .with_context(no_reset_password=True)
            .create(
                {
                    "name": login,
                    "login": login,
                    "email": f"{login}@example.com",
                    "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
                }
            )
        )

    def test_batch_create_accumulates(self):
        """Several rows for one user in a single create() must all count."""
        user = self._user("karma_batch")
        self.env.flush_all()
        self.Tracking.create(
            [{"user_id": user.id, "gain": 10}, {"user_id": user.id, "gain": 5}]
        )
        self.env.flush_all()
        user.invalidate_recordset()
        self.assertEqual(user.karma, 15, "Both rows of a batch must be counted")

    def test_backdated_row_still_counts(self):
        """A row inserted with an older tracking_date must not be swallowed."""
        user = self._user("karma_backdate")
        user.karma = 150
        self.env.flush_all()
        self.Tracking.create(
            [
                {
                    "user_id": user.id,
                    "gain": 25,
                    "tracking_date": fields.Datetime.now() - timedelta(days=365),
                }
            ]
        )
        self.env.flush_all()
        user.invalidate_recordset()
        self.assertEqual(user.karma, 175, "Backdated gains must still apply")

    def test_consolidation_preserves_pending_recompute(self):
        """Consolidating must not discard a karma recompute pending in the
        same transaction."""
        user = self._user("karma_consol")
        self.env.flush_all()
        old = fields.Datetime.now() - timedelta(days=70)
        self.Tracking.create([{"user_id": user.id, "gain": 30, "tracking_date": old}])
        self.env.flush_all()
        user.invalidate_recordset()
        self.assertEqual(user.karma, 30)

        user._add_karma(40, reason="pending during consolidation")
        self.Tracking._consolidate_cron()
        self.env.flush_all()
        user.invalidate_recordset()
        self.assertEqual(
            user.karma, 70, "Consolidation must be karma-neutral, not destructive"
        )

    def test_consolidation_is_karma_neutral(self):
        """CONTROL: consolidation alone changes no karma."""
        user = self._user("karma_neutral")
        self.env.flush_all()
        old = fields.Datetime.now() - timedelta(days=70)
        self.Tracking.create([{"user_id": user.id, "gain": 30, "tracking_date": old}])
        self.env.flush_all()
        user.invalidate_recordset()
        before = user.karma
        self.Tracking._consolidate_cron()
        self.env.flush_all()
        user.invalidate_recordset()
        self.assertEqual(user.karma, before, "CONTROL: consolidation is neutral")


class TestGoalStateMachine(common.TransactionCase):
    """State transitions must not depend on the measured value changing."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user_test = (
            cls.env["res.users"]
            .with_context(no_reset_password=True)
            .create(
                {
                    "name": "Goal State User",
                    "login": "goal_state_user",
                    "email": "gs@example.com",
                    "group_ids": [(6, 0, [cls.env.ref("base.group_user").id])],
                }
            )
        )
        cls.model_goal = cls.env["ir.model"]._get("gamification.goal")

    def _definition(self, code):
        return self.env["gamification.goal.definition"].create(
            {
                "name": "State Def",
                "computation_mode": "python",
                "model_id": self.model_goal.id,
                "compute_code": code,
                "condition": "higher",
            }
        )

    def _goal(self, definition, target, current, end_date, state="inprogress"):
        return self.env["gamification.goal"].create(
            {
                "definition_id": definition.id,
                "user_id": self.user_test.id,
                "target_goal": target,
                "current": current,
                "state": state,
                "start_date": date.today() - timedelta(days=30),
                "end_date": end_date,
            }
        )

    def test_expired_goal_fails_even_when_value_flat(self):
        goal = self._goal(
            self._definition("result = 5"),
            target=100,
            current=5,
            end_date=date.today() - timedelta(days=1),
        )
        goal.update_goal()
        self.assertEqual(goal.state, "failed")
        self.assertTrue(goal.closed)

    def test_expired_goal_fails_when_value_changed(self):
        """CONTROL: the path that always worked still works."""
        goal = self._goal(
            self._definition("result = 5"),
            target=100,
            current=3,
            end_date=date.today() - timedelta(days=1),
        )
        goal.update_goal()
        self.assertEqual(goal.current, 5)
        self.assertEqual(goal.state, "failed")

    def test_reached_goal_reverts_when_value_drops(self):
        goal = self._goal(
            self._definition("result = 20"), target=100, current=0, end_date=False
        )
        goal.write({"state": "reached"})
        goal.update_goal()
        self.assertEqual(goal.state, "inprogress")

    def test_goal_becomes_reached(self):
        """CONTROL: crossing the target still sets reached."""
        goal = self._goal(
            self._definition("result = 150"), target=100, current=0, end_date=False
        )
        goal.update_goal()
        self.assertEqual(goal.state, "reached")

    def test_draft_goal_untouched_by_recomputation(self):
        """A draft goal must not be auto-started by an update."""
        goal = self._goal(
            self._definition("result = 150"),
            target=100,
            current=0,
            end_date=False,
            state="draft",
        )
        goal.update_goal()
        self.assertEqual(goal.state, "draft")


class TestMentorshipSecurity(common.TransactionCase):
    """A mentor must not be able to mint karma for themselves."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        emp = cls.env.ref("base.group_user")
        Users = cls.env["res.users"].with_context(no_reset_password=True)
        cls.attacker = Users.create(
            {
                "name": "Mentor Attacker",
                "login": "m_attacker",
                "email": "ma@example.com",
                "group_ids": [(6, 0, [emp.id])],
            }
        )
        cls.victim = Users.create(
            {
                "name": "Mentee Victim",
                "login": "m_victim",
                "email": "mv@example.com",
                "group_ids": [(6, 0, [emp.id])],
            }
        )

    def test_employee_cannot_set_own_payout(self):
        """Reward fields are manager-only, so the amount is never attacker-set."""
        with self.assertRaises(AccessError):
            self.env["gamification.mentorship"].with_user(self.attacker).create(
                {
                    "mentor_id": self.attacker.id,
                    "mentee_id": self.victim.id,
                    "mentor_karma_on_completion": 999999,
                }
            )

    def test_mentor_cannot_complete_own_mentorship(self):
        """Completion pays the mentor, so the mentor may not trigger it."""
        mentorship = self.env["gamification.mentorship"].create(
            {"mentor_id": self.attacker.id, "mentee_id": self.victim.id}
        )
        with self.assertRaises(AccessError):
            mentorship.with_user(self.attacker).action_complete()

    def test_mentee_can_complete_and_mentor_is_paid(self):
        """CONTROL: the legitimate path still works and still pays."""
        mentorship = self.env["gamification.mentorship"].create(
            {
                "mentor_id": self.attacker.id,
                "mentee_id": self.victim.id,
                "mentor_karma_on_completion": 100,
            }
        )
        before = self.attacker.karma
        mentorship.with_user(self.victim).action_complete()
        self.attacker.invalidate_recordset()
        self.assertEqual(mentorship.state, "completed")
        self.assertEqual(self.attacker.karma, before + 100)

    def test_employee_cannot_see_third_party_mentorship(self):
        """The record rule hides pairings the user is not part of."""
        other_a = (
            self.env["res.users"]
            .with_context(no_reset_password=True)
            .create(
                {
                    "name": "Other A",
                    "login": "other_a",
                    "email": "oa@example.com",
                    "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
                }
            )
        )
        mentorship = self.env["gamification.mentorship"].create(
            {"mentor_id": other_a.id, "mentee_id": self.victim.id}
        )
        visible = (
            self.env["gamification.mentorship"]
            .with_user(self.attacker)
            .search([("id", "=", mentorship.id)])
        )
        self.assertFalse(visible, "Third-party mentorship must not be visible")


class TestStreakCronIdempotency(common.TransactionCase):
    def test_repeated_cron_runs_are_noops(self):
        """Running the streak cron repeatedly in one day must not burn
        freeze days or break a streak."""
        user = (
            self.env["res.users"]
            .with_context(no_reset_password=True)
            .create(
                {
                    "name": "Streak User",
                    "login": "streak_idem",
                    "email": "si@example.com",
                    "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
                }
            )
        )
        stype = self.env["gamification.streak.type"].create(
            {
                "name": "Idem Streak",
                "model_id": self.env.ref("base.model_res_partner").id,
                "date_field_id": self.env["ir.model.fields"]
                ._get("res.partner", "create_date")
                .id,
                "domain": "[('id','=',-1)]",  # never matches
            }
        )
        Streak = self.env["gamification.streak"]
        streak = Streak.create(
            {
                "user_id": user.id,
                "streak_type_id": stype.id,
                "current_count": 10,
                "state": "active",
                "last_activity_date": fields.Date.today() - timedelta(days=1),
            }
        )
        streak.freeze_remaining = 2
        self.env.flush_all()

        Streak._cron_update_streaks()
        after_first = streak.freeze_remaining
        self.assertEqual(after_first, 1, "First run consumes exactly one freeze day")

        for _ in range(3):
            Streak._cron_update_streaks()
        self.assertEqual(
            streak.freeze_remaining,
            after_first,
            "Repeat runs in the same day must be no-ops",
        )
        self.assertEqual(streak.current_count, 10, "Streak must survive repeat runs")
        self.assertEqual(streak.state, "active")


class TestStreakTimezone(common.TransactionCase):
    """A streak day is the user's calendar day, not a UTC day.

    Storage stays UTC; only the day *window* is resolved in the user's
    timezone, following the ``lunch.supplier`` / ``hr.employee._get_tz``
    pattern used elsewhere in core for calendar-day business logic.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.stype = cls.env["gamification.streak.type"].create(
            {
                "name": "TZ Streak",
                "model_id": cls.env["ir.model"]._get("res.partner").id,
                "date_field_id": cls.env["ir.model.fields"]
                ._get("res.partner", "create_date")
                .id,
                "domain": "[('user_id','=',user.id)]",
            }
        )
        cls.monday = date(2026, 7, 13)
        cls.tuesday = date(2026, 7, 14)

    def _user_with_activity(self, login, tz, stored_utc):
        user = (
            self.env["res.users"]
            .with_context(no_reset_password=True)
            .create(
                {
                    "name": login,
                    "login": login,
                    "email": f"{login}@example.com",
                    "tz": tz,
                    "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
                }
            )
        )
        partner = self.env["res.partner"].create(
            {"name": f"{login} work", "user_id": user.id}
        )
        self.env.cr.execute(
            "UPDATE res_partner SET create_date=%s WHERE id=%s",
            (stored_utc, partner.id),
        )
        self.env.flush_all()
        self.env.invalidate_all()
        return user

    def test_evening_work_west_of_utc_counts_same_day(self):
        """UTC-6, Monday 19:00 local (Tuesday 01:00 UTC) is Monday activity."""
        user = self._user_with_activity(
            "tz_west", "America/Mexico_City", "2026-07-14 01:00:00"
        )
        self.assertTrue(self.stype._check_user_activity(user, self.monday))
        self.assertFalse(self.stype._check_user_activity(user, self.tuesday))

    def test_early_work_east_of_utc_counts_same_day(self):
        """UTC+9, Tuesday 07:00 local (Monday 22:00 UTC) is Tuesday activity."""
        user = self._user_with_activity("tz_east", "Asia/Tokyo", "2026-07-13 22:00:00")
        self.assertFalse(self.stype._check_user_activity(user, self.monday))
        self.assertTrue(self.stype._check_user_activity(user, self.tuesday))

    def test_user_without_timezone_uses_utc_day(self):
        """CONTROL: no tz set behaves exactly as before."""
        user = self._user_with_activity("tz_unset", False, "2026-07-13 12:00:00")
        self.assertTrue(self.stype._check_user_activity(user, self.monday))
        self.assertFalse(self.stype._check_user_activity(user, self.tuesday))

    def test_batch_check_groups_users_by_timezone(self):
        """Users in different timezones are bucketed independently in one batch."""
        west = self._user_with_activity(
            "tz_batch_west", "America/Mexico_City", "2026-07-14 01:00:00"
        )
        east = self._user_with_activity(
            "tz_batch_east", "Asia/Tokyo", "2026-07-13 22:00:00"
        )
        monday_active = self.stype._check_user_activity_batch(west + east, self.monday)
        self.assertEqual(
            monday_active,
            {west.id},
            "Only the UTC-6 user worked on Monday in their own timezone",
        )
        tuesday_active = self.stype._check_user_activity_batch(
            west + east, self.tuesday
        )
        self.assertEqual(tuesday_active, {east.id})


class TestCronErrorIsolation(common.TransactionCase):
    """One broken record must not abort a whole cron run."""

    def _user(self, login):
        return (
            self.env["res.users"]
            .with_context(no_reset_password=True)
            .create(
                {
                    "name": login,
                    "login": login,
                    "email": f"{login}@example.com",
                    "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
                }
            )
        )

    def test_bad_achievement_does_not_block_the_others(self):
        """A poison trigger_domain must not stop later achievements."""
        user = self._user("ach_isolation")
        partner_model = self.env["ir.model"]._get("res.partner")
        self.env["res.partner"].create({"name": "Isolation Partner"})

        # Ordered by sequence: the broken one is evaluated first.
        self.env["gamification.achievement"].create(
            {
                "name": "Broken Achievement",
                "sequence": 1,
                "model_id": partner_model.id,
                "trigger_domain": "[('field_that_does_not_exist','=',1)]",
                "trigger_count": 1,
                "karma_reward": 10,
            }
        )
        good = self.env["gamification.achievement"].create(
            {
                "name": "Good Achievement",
                "sequence": 2,
                "model_id": partner_model.id,
                "trigger_domain": "[]",
                "trigger_count": 1,
                "karma_reward": 10,
            }
        )
        self.env.flush_all()

        # Must not raise, and must still process the healthy achievement.
        self.env["gamification.achievement"]._cron_check_achievements()
        self.env.flush_all()

        unlocked = self.env["gamification.achievement.unlock"].search_count(
            [("achievement_id", "=", good.id), ("user_id", "=", user.id)]
        )
        self.assertTrue(
            unlocked,
            "A broken achievement must not prevent later ones from unlocking",
        )

    def test_bad_streak_type_does_not_block_the_others(self):
        """A poison streak domain must not stop later streaks."""
        user_bad = self._user("streak_bad")
        user_good = self._user("streak_good")
        partner_field = self.env["ir.model.fields"]._get("res.partner", "create_date")
        partner_model = self.env.ref("base.model_res_partner")
        Streak = self.env["gamification.streak"]

        bad_type = self.env["gamification.streak.type"].create(
            {
                "name": "Broken Streak",
                "model_id": partner_model.id,
                "date_field_id": partner_field.id,
                "domain": "[('nope_not_a_field','=',1)]",
            }
        )
        good_type = self.env["gamification.streak.type"].create(
            {
                "name": "Good Streak",
                "model_id": partner_model.id,
                "date_field_id": partner_field.id,
                "domain": "[('id','=',-1)]",
            }
        )
        yesterday = fields.Date.today() - timedelta(days=1)
        Streak.create(
            {
                "user_id": user_bad.id,
                "streak_type_id": bad_type.id,
                "current_count": 3,
                "state": "active",
                "last_activity_date": yesterday,
            }
        )
        good_streak = Streak.create(
            {
                "user_id": user_good.id,
                "streak_type_id": good_type.id,
                "current_count": 3,
                "state": "active",
                "last_activity_date": yesterday,
            }
        )
        good_streak.freeze_remaining = 1
        self.env.flush_all()

        Streak._cron_update_streaks()

        self.assertEqual(
            good_streak.freeze_remaining,
            0,
            "The healthy streak must still be processed despite a broken one",
        )
        self.assertEqual(
            good_streak.last_checked_date,
            fields.Date.today(),
            "The healthy streak must be marked as checked",
        )


class TestSkillTreeWiring(common.TransactionCase):
    """The skill tree must actually unlock when its quest completes."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = (
            cls.env["res.users"]
            .with_context(no_reset_password=True)
            .create(
                {
                    "name": "Skill User",
                    "login": "skill_user",
                    "email": "sk@example.com",
                    "group_ids": [(6, 0, [cls.env.ref("base.group_user").id])],
                }
            )
        )
        cls.quest = cls.env["gamification.quest"].create({"name": "Skill Quest"})
        cls.tree = cls.env["gamification.skill.tree"].create({"name": "Tree"})
        cls.root = cls.env["gamification.skill.node"].create(
            {
                "name": "Root Node",
                "tree_id": cls.tree.id,
                "quest_id": cls.quest.id,
                "karma_reward": 30,
            }
        )
        cls.leaf = cls.env["gamification.skill.node"].create(
            {
                "name": "Leaf Node",
                "tree_id": cls.tree.id,
                "prerequisite_ids": [(6, 0, [cls.root.id])],
                "karma_reward": 40,
            }
        )

    def _complete_quest(self):
        enrollment = self.env["gamification.quest.enrollment"].create(
            {"quest_id": self.quest.id, "user_id": self.user.id}
        )
        enrollment._complete_quest()
        return enrollment

    def test_quest_completion_unlocks_linked_node(self):
        """Completing the quest unlocks the node gated on it."""
        self._complete_quest()
        unlocked = self.env["gamification.skill.node.unlock"].search_count(
            [("node_id", "=", self.root.id), ("user_id", "=", self.user.id)]
        )
        self.assertTrue(unlocked, "Quest-linked skill node must unlock on completion")

    def test_unlock_cascades_to_dependents(self):
        """Unlocking the root satisfies the leaf's only prerequisite."""
        self._complete_quest()
        leaf_unlocked = self.env["gamification.skill.node.unlock"].search_count(
            [("node_id", "=", self.leaf.id), ("user_id", "=", self.user.id)]
        )
        self.assertTrue(
            leaf_unlocked, "A node whose prerequisites are now met must cascade-unlock"
        )

    def test_unlock_grants_karma(self):
        """CONTROL: both nodes' karma rewards are actually granted."""
        before = self.user.karma
        self._complete_quest()
        self.user.invalidate_recordset()
        # quest 0 karma + root 30 + leaf 40
        self.assertEqual(self.user.karma, before + 70)

    def test_unlock_is_idempotent(self):
        """Re-running the unlock must not double-grant."""
        self._complete_quest()
        karma_after_first = self.user.karma
        self.env["gamification.skill.node"]._unlock_nodes_for_quest(
            self.env["gamification.quest.enrollment"].search(
                [("quest_id", "=", self.quest.id), ("user_id", "=", self.user.id)]
            )
        )
        self.user.invalidate_recordset()
        self.assertEqual(
            self.user.karma,
            karma_after_first,
            "Already-unlocked nodes must not re-grant",
        )

    def test_prerequisite_cycle_rejected(self):
        """A prerequisite cycle must be rejected at write time."""
        a = self.env["gamification.skill.node"].create(
            {"name": "Cycle A", "tree_id": self.tree.id}
        )
        b = self.env["gamification.skill.node"].create(
            {
                "name": "Cycle B",
                "tree_id": self.tree.id,
                "prerequisite_ids": [(6, 0, [a.id])],
            }
        )
        with self.assertRaises(ValidationError):
            a.write({"prerequisite_ids": [(6, 0, [b.id])]})


class TestNudgeBudget(common.TransactionCase):
    def test_low_progress_user_keeps_nudge_eligibility(self):
        """Users who receive no nudge must not have their cooldown consumed."""
        definition = self.env["gamification.goal.definition"].create(
            {"name": "Nudge Def", "computation_mode": "manually", "condition": "higher"}
        )
        user = (
            self.env["res.users"]
            .with_context(no_reset_password=True)
            .create(
                {
                    "name": "Low Progress",
                    "login": "nudge_low_r",
                    "email": "nl@example.com",
                    "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
                }
            )
        )
        self.env["gamification.goal"].sudo().create(
            {
                "definition_id": definition.id,
                "user_id": user.id,
                "target_goal": 100,
                "current": 10,
                "state": "inprogress",
                "closed": False,
            }
        )
        self.env["res.users"]._nudge_goals_almost_done()
        user.invalidate_recordset(["last_gamification_nudge_date"])
        self.assertFalse(user.last_gamification_nudge_date)

    def test_high_progress_user_is_nudged(self):
        """CONTROL: a user at 90% is nudged and marked."""
        definition = self.env["gamification.goal.definition"].create(
            {"name": "Nudge Def", "computation_mode": "manually", "condition": "higher"}
        )
        user = (
            self.env["res.users"]
            .with_context(no_reset_password=True)
            .create(
                {
                    "name": "High Progress",
                    "login": "nudge_high_r",
                    "email": "nh@example.com",
                    "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
                }
            )
        )
        self.env["gamification.goal"].sudo().create(
            {
                "definition_id": definition.id,
                "user_id": user.id,
                "target_goal": 100,
                "current": 90,
                "state": "inprogress",
                "closed": False,
            }
        )
        self.env["res.users"]._nudge_goals_almost_done()
        user.invalidate_recordset(["last_gamification_nudge_date"])
        self.assertEqual(user.last_gamification_nudge_date, fields.Date.today())


class TestProfilePrivacy(common.TransactionCase):
    def test_user_can_set_own_visibility(self):
        """The privacy control must be reachable by the person it protects."""
        user = (
            self.env["res.users"]
            .with_context(no_reset_password=True)
            .create(
                {
                    "name": "Privacy User",
                    "login": "privacy_user",
                    "email": "pu@example.com",
                    "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
                }
            )
        )
        user.with_user(user).write({"gamification_visibility": "private"})
        self.assertEqual(user.gamification_visibility, "private")

    def test_private_user_activity_hidden_from_others(self):
        """A private profile's activity rows are hidden at the ORM layer, not
        only inside the curated feed helper."""
        emp = self.env.ref("base.group_user")
        Users = self.env["res.users"].with_context(no_reset_password=True)
        private = Users.create(
            {
                "name": "Private One",
                "login": "priv_one",
                "email": "p1@example.com",
                "group_ids": [(6, 0, [emp.id])],
                "gamification_visibility": "private",
            }
        )
        observer = Users.create(
            {
                "name": "Observer",
                "login": "observer_one",
                "email": "o1@example.com",
                "group_ids": [(6, 0, [emp.id])],
            }
        )
        activity = self.env["gamification.activity"].create(
            {
                "user_id": private.id,
                "activity_type": "level_up",
                "summary": "secret activity",
            }
        )
        self.env.flush_all()
        visible = (
            self.env["gamification.activity"]
            .with_user(observer)
            .search([("id", "=", activity.id)])
        )
        self.assertFalse(visible, "Private user's activity must not be readable")

    def test_public_user_activity_visible(self):
        """CONTROL: a public profile's activity remains visible."""
        emp = self.env.ref("base.group_user")
        Users = self.env["res.users"].with_context(no_reset_password=True)
        public = Users.create(
            {
                "name": "Public One",
                "login": "pub_one",
                "email": "pb1@example.com",
                "group_ids": [(6, 0, [emp.id])],
                "gamification_visibility": "public",
            }
        )
        observer = Users.create(
            {
                "name": "Observer Two",
                "login": "observer_two",
                "email": "o2@example.com",
                "group_ids": [(6, 0, [emp.id])],
            }
        )
        activity = self.env["gamification.activity"].create(
            {
                "user_id": public.id,
                "activity_type": "level_up",
                "summary": "public activity",
            }
        )
        self.env.flush_all()
        visible = (
            self.env["gamification.activity"]
            .with_user(observer)
            .search([("id", "=", activity.id)])
        )
        self.assertTrue(visible, "CONTROL: public activity stays visible")
