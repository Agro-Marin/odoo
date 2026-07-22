"""Tests for the account code/name string splitter."""

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSplitCodeName(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Account = cls.env["account.account"]

    def test_split_code_and_name(self):
        """A leading numeric code is split off the name."""
        self.assertEqual(
            self.Account._split_code_name("101000 Cash"), ("101000", "Cash")
        )

    def test_split_name_only(self):
        """A string without a leading code yields an empty code (boundary)."""
        code, name = self.Account._split_code_name("Cash")
        self.assertFalse(code)
        self.assertEqual(name, "Cash")

    def test_split_empty_string(self):
        """An empty input yields empty code and name (boundary)."""
        self.assertEqual(self.Account._split_code_name(""), (None, ""))

    def test_split_trims_surrounding_whitespace_in_name(self):
        """The name part is stripped of surrounding whitespace."""
        code, name = self.Account._split_code_name("400100   Suppliers  ")
        self.assertEqual(code, "400100")
        self.assertEqual(name, "Suppliers")
