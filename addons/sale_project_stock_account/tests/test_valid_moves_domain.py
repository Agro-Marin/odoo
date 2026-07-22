"""Tests for the anglo-saxon exclusion in the valid-moves domain."""

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestValidMovesDomain(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.move = cls.env["stock.move"]
        cls.company = cls.env.user.company_id

    def _domain_str(self):
        return str(self.move._get_valid_moves_domain())

    def test_anglo_saxon_excludes_reinvoiced_products(self):
        """With anglo-saxon accounting, reinvoiced products are excluded."""
        self.company.anglo_saxon_accounting = True
        self.assertIn("expense_policy", self._domain_str())

    def test_without_anglo_saxon_keeps_base_domain(self):
        """Without anglo-saxon accounting, the extra clause is absent (boundary)."""
        self.company.anglo_saxon_accounting = False
        self.assertNotIn("expense_policy", self._domain_str())
