from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import common


class TestGoalDefinition(common.TransactionCase):
    """Test gamification.goal.definition validation methods."""

    @classmethod
    def setUpClass(cls):
        """Set up shared test data for goal definition tests."""
        super().setUpClass()
        cls.partner_model = cls.env["ir.model"].search(
            [("model", "=", "res.partner")], limit=1
        )

    def _create_definition(self, vals=None):
        """Create a goal definition with sensible defaults.

        :param vals: Optional dict to override default values.
        :return: A ``gamification.goal.definition`` record.
        """
        defaults = {
            "name": "Test Definition",
            "computation_mode": "count",
            "model_id": self.partner_model.id,
            "domain": "[]",
        }
        if vals:
            defaults.update(vals)
        return self.env["gamification.goal.definition"].create(defaults)

    @patch("odoo.addons.mail.models.mail_thread.MailThread._notify_thread")
    def test_check_domain_validity_invalid(self, _mock_notify):
        """Verify that an invalid domain string raises UserError on create."""
        with self.assertRaises(UserError):
            self._create_definition({"domain": "not a valid domain"})

    @patch("odoo.addons.mail.models.mail_thread.MailThread._notify_thread")
    def test_check_domain_validity_valid(self, _mock_notify):
        """Verify that a valid domain does not raise any error."""
        definition = self._create_definition(
            {
                "domain": "[('active', '=', True)]",
            }
        )
        self.assertTrue(definition.id, "Definition should be created successfully")

    @patch("odoo.addons.mail.models.mail_thread.MailThread._notify_thread")
    def test_compute_full_suffix_without_monetary(self, _mock_notify):
        """Verify full_suffix equals the plain suffix when monetary is False."""
        definition = self._create_definition(
            {
                "suffix": "tasks",
                "monetary": False,
                "computation_mode": "manually",
            }
        )
        self.assertEqual(definition.full_suffix, "tasks")

    @patch("odoo.addons.mail.models.mail_thread.MailThread._notify_thread")
    def test_compute_full_suffix_with_monetary(self, _mock_notify):
        """Verify full_suffix includes currency symbol when monetary is True."""
        definition = self._create_definition(
            {
                "suffix": "tasks",
                "monetary": False,
                "computation_mode": "manually",
            }
        )
        self.assertEqual(definition.full_suffix, "tasks")

        definition.monetary = True
        currency_symbol = self.env.company.currency_id.symbol or "¤"
        self.assertIn(currency_symbol, definition.full_suffix)
        self.assertIn("tasks", definition.full_suffix)
        self.assertEqual(definition.full_suffix, f"{currency_symbol} tasks")
