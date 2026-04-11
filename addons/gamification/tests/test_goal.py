from odoo.exceptions import UserError
from odoo.tests import common


class TestGoal(common.TransactionCase):
    """Tests for gamification.goal model methods."""

    @classmethod
    def setUpClass(cls):
        """Set up test data for goal tests."""
        super().setUpClass()

        # Patch email sending to avoid side effects
        cls.env = cls.env(context=dict(cls.env.context, no_remind_goal=True))

        cls.user_test = (
            cls.env["res.users"]
            .with_context(no_reset_password=True)
            .create(
                {
                    "name": "Goal Test User",
                    "login": "goal_test_user",
                    "email": "goal_test@example.com",
                    "group_ids": [(6, 0, [cls.env.ref("base.group_user").id])],
                }
            )
        )

        cls.model_goal = cls.env["ir.model"].search(
            [("model", "=", "gamification.goal")], limit=1
        )

        cls.definition_python = cls.env["gamification.goal.definition"].create(
            {
                "name": "Test Python Definition",
                "computation_mode": "python",
                "model_id": cls.model_goal.id,
                "compute_code": "result = 42",
                "condition": "higher",
            }
        )

        cls.definition_manual = cls.env["gamification.goal.definition"].create(
            {
                "name": "Test Manual Definition",
                "computation_mode": "manually",
                "condition": "higher",
            }
        )

    def _create_goal(self, definition, target=100, current=0, state="inprogress"):
        """Create a goal with common defaults."""
        return self.env["gamification.goal"].create(
            {
                "definition_id": definition.id,
                "user_id": self.user_test.id,
                "target_goal": target,
                "current": current,
                "state": state,
            }
        )

    def test_update_goal_python_mode(self):
        """Test that update_goal evaluates Python code and sets current value."""
        goal = self._create_goal(self.definition_python, target=100)
        goal.update_goal()
        self.assertEqual(
            goal.current, 42, "Goal current should be set to the result of compute_code"
        )

    def test_update_goal_python_mode_invalid_result(self):
        """Test that a non-numeric result from compute_code does not crash or update current."""
        definition = self.env["gamification.goal.definition"].create(
            {
                "name": "Invalid Python Definition",
                "computation_mode": "python",
                "model_id": self.model_goal.id,
                "compute_code": 'result = "not_a_number"',
                "condition": "higher",
            }
        )
        goal = self._create_goal(definition, target=100)
        original_current = goal.current
        goal.update_goal()
        self.assertEqual(
            goal.current,
            original_current,
            "Goal current should remain unchanged when compute_code returns a non-numeric value",
        )

    def test_get_completion_higher_at_100(self):
        """Test that completeness is capped at 100% when current exceeds target."""
        goal = self._create_goal(self.definition_manual, target=100, current=150)
        self.assertEqual(
            goal.completeness, 100.0, "Completeness should be capped at 100.0"
        )

    def test_get_completion_higher_partial(self):
        """Test partial completion percentage calculation."""
        goal = self._create_goal(self.definition_manual, target=100, current=50)
        self.assertEqual(
            goal.completeness, 50.0, "Completeness should be 50.0 for half completion"
        )

    def test_get_completion_target_zero(self):
        """Test that zero target does not cause division by zero.

        When target=0 and condition='higher', current >= target is True,
        so completeness should be 100% (goal is trivially reached).
        """
        goal = self._create_goal(self.definition_manual, target=0, current=50)
        self.assertEqual(
            goal.completeness,
            100.0,
            "Completeness should be 100 when target is zero (trivially reached)",
        )

    def test_goal_write_blocks_definition_change(self):
        """Test that changing definition_id on a non-draft goal raises UserError."""
        goal = self._create_goal(self.definition_manual, state="inprogress")

        other_definition = self.env["gamification.goal.definition"].create(
            {
                "name": "Other Definition",
                "computation_mode": "manually",
                "condition": "higher",
            }
        )

        with self.assertRaises(
            UserError,
            msg="Changing definition on a non-draft goal should raise UserError",
        ):
            goal.write({"definition_id": other_definition.id})
