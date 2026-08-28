from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSplitCodeName(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Account = cls.env["account.account"]

    def test_split_code_and_name(self):
        self.assertEqual(
            self.Account._split_code_name("101000 Cash"), ("101000", "Cash")
        )

    def test_split_name_only(self):
        code, name = self.Account._split_code_name("Cash")
        self.assertFalse(code)
        self.assertEqual(name, "Cash")

    def test_split_empty_string(self):
        self.assertEqual(self.Account._split_code_name(""), (None, ""))

    def test_split_trims_surrounding_whitespace_in_name(self):
        code, name = self.Account._split_code_name("400100   Suppliers  ")
        self.assertEqual(code, "400100")
        self.assertEqual(name, "Suppliers")
