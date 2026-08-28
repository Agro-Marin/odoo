from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestAccountCopyAndName(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Account = cls.env["account.account"]

    def test_copy_generates_new_code_and_copy_name(self):
        account = self.Account.create(
            {"code": "203000", "name": "Seed", "account_type": "asset_current"}
        )
        copy = account.copy()
        self.assertNotEqual(copy.code, account.code)
        self.assertTrue(copy.code)
        self.assertIn("Seed (copy)", str(copy.name))

    def test_name_create_outside_import_is_blocked(self):
        with self.assertRaises(ValidationError):
            self.Account.name_create("300000 Something")

    def test_name_create_on_import_splits_code_and_name(self):
        _id, _display = self.Account.with_context(import_file=True).name_create(
            "400000 Imported Account"
        )
        account = self.Account.browse(_id)
        self.assertEqual(account.code, "400000")
        self.assertEqual(account.name, "Imported Account")

    def test_search_display_name_matches_code_prefix(self):
        account = self.Account.create(
            {"code": "700000", "name": "Revenue", "account_type": "income"}
        )
        found = self.Account.search([("display_name", "=", "700000 Revenue")])
        self.assertIn(account, found)

    def test_search_display_name_in_operator(self):
        account = self.Account.create(
            {"code": "710000", "name": "OtherRevenue", "account_type": "income"}
        )
        found = self.Account.search([("display_name", "in", ["OtherRevenue"])])
        self.assertIn(account, found)
