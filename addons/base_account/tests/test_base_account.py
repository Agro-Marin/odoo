"""Fast, self-contained tests for the ``base_account`` foundation.

These exercise the extracted chart-of-accounts logic without pulling in the
heavy ``account`` accounting stack (journals, taxes, moves).  The downstream
``account`` module has its own ``post_install`` suite; the point here is that
the foundation can be validated -- and refactored -- on its own.
"""

from odoo import Command
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestBaseAccount(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Account = cls.env["account.account"]

    # ------------------------------------------------------------------
    # _split_code_name
    # ------------------------------------------------------------------

    def test_split_code_name(self):
        cases = [
            ("101000 Cash", ("101000", "Cash")),
            ("Cash", (None, "Cash")),
            ("101000", ("101000", "")),
            ("123-A Cash Register", ("123-A", "Cash Register")),
            ("", (None, "")),
        ]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(self.Account._split_code_name(value), expected)

    # ------------------------------------------------------------------
    # Code validation
    # ------------------------------------------------------------------

    def test_code_regex_rejects_invalid_chars(self):
        for bad in ("10 00", "10#0", "abc$"):
            with self.subTest(code=bad), self.assertRaises(ValidationError):
                self.Account.create(
                    {"code": bad, "name": "Bad", "account_type": "asset_current"}
                )

    def test_code_regex_accepts_valid_chars(self):
        acc = self.Account.create(
            {"code": "10.01-A/B", "name": "Ok", "account_type": "asset_current"}
        )
        self.assertEqual(acc.code, "10.01-A/B")

    # ------------------------------------------------------------------
    # _search_new_account_code
    # ------------------------------------------------------------------

    def test_search_new_account_code(self):
        self.Account.create(
            {"code": "203000", "name": "Seed", "account_type": "asset_current"}
        )
        self.assertEqual(self.Account._search_new_account_code("203000"), "203001")

    def test_search_new_account_code_copy_fallback(self):
        self.Account.create(
            {"code": "hello", "name": "Seed", "account_type": "asset_current"}
        )
        self.assertEqual(self.Account._search_new_account_code("hello"), "hello.copy")

    # ------------------------------------------------------------------
    # _get_closest_parent_account (the method optimised in this change)
    # ------------------------------------------------------------------

    def test_closest_parent_inherits_type_and_tags(self):
        self.Account.create(
            {
                "code": "400000",
                "name": "Parent",
                "account_type": "expense",
                "tag_ids": [Command.create({"name": "ClosestParentTag"})],
            }
        )
        child = self.Account.create({"code": "400001", "name": "Child"})
        self.assertEqual(child.account_type, "expense")
        self.assertEqual(child.tag_ids.name, "ClosestParentTag")

    def test_closest_parent_default_when_no_parent(self):
        # A code that sorts before every existing account falls back to default.
        child = self.Account.create({"code": "000001", "name": "Orphan"})
        self.assertEqual(child.account_type, "asset_current")

    def test_closest_parent_batch_consistency(self):
        """Optimised bisect list must give the same result as per-row lookup."""
        self.Account.create({"code": "500000", "name": "A", "account_type": "income"})
        self.Account.create({"code": "600000", "name": "B", "account_type": "expense"})
        children = self.Account.create(
            [
                {"code": "500500", "name": "c1"},
                {"code": "600500", "name": "c2"},
                {"code": "500900", "name": "c3"},
            ]
        )
        self.assertEqual(
            children.mapped("account_type"), ["income", "expense", "income"]
        )

    # ------------------------------------------------------------------
    # Reconcile constraints
    # ------------------------------------------------------------------

    def test_receivable_must_be_reconcilable(self):
        acc = self.Account.create(
            {"code": "110000", "name": "Recv", "account_type": "asset_receivable"}
        )
        self.assertTrue(acc.reconcile)
        with self.assertRaises(ValidationError):
            acc.reconcile = False

    def test_off_balance_cannot_reconcile(self):
        with self.assertRaises(UserError):
            self.Account.create(
                {
                    "code": "990000",
                    "name": "OffBal",
                    "account_type": "off_balance",
                    "reconcile": True,
                }
            )

    # ------------------------------------------------------------------
    # Derived fields
    # ------------------------------------------------------------------

    def test_internal_group_and_initial_balance(self):
        income = self.Account.create(
            {"code": "700000", "name": "Rev", "account_type": "income"}
        )
        self.assertEqual(income.internal_group, "income")
        self.assertFalse(income.include_initial_balance)

        asset = self.Account.create(
            {"code": "150000", "name": "Asset", "account_type": "asset_non_current"}
        )
        self.assertEqual(asset.internal_group, "asset")
        self.assertTrue(asset.include_initial_balance)

    def test_display_name(self):
        acc = self.Account.create(
            {"code": "160000", "name": "Widget", "account_type": "asset_current"}
        )
        self.assertEqual(acc.display_name, "160000 Widget")

    def test_default_get_preserves_leading_zeros(self):
        # A fully-numeric quick-create name is treated as a code; leading zeros
        # must survive ("0001" is a different account code from "1").
        for name, expected_code in [
            ("0001", "0001"),
            ("007", "007"),
            ("101000", "101000"),
        ]:
            with self.subTest(name=name):
                defaults = self.Account.with_context(default_name=name).default_get(
                    ["name", "code"]
                )
                self.assertEqual(defaults.get("code"), expected_code)
                self.assertFalse(defaults.get("name"))


@tagged("post_install", "-at_install")
class TestAccountRoot(TransactionCase):
    def test_from_account_code(self):
        Root = self.env["account.root"]
        self.assertFalse(Root._from_account_code(False).id)
        root = Root._from_account_code("101000")
        self.assertEqual(root.id, "10")
        self.assertEqual(root.name, "10")
        self.assertEqual(root.parent_id.id, "1")

    def test_search_parent_of(self):
        Root = self.env["account.root"]
        roots = Root.search([("id", "parent_of", ["10"])])
        self.assertEqual(sorted(roots.ids), ["1", "10"])


@tagged("post_install", "-at_install")
class TestAccountCodeMapping(TransactionCase):
    def test_direct_access_is_blocked(self):
        # The mapping is virtual; it may only be reached through an account.
        with self.assertRaises(UserError):
            self.env["account.code.mapping"].search([])

    def test_offset_roundtrip(self):
        # The virtual mapping id encodes (account_id, company_id); check both the
        # ``_search`` path and the ``code_mapping_ids`` One2many decode back to the
        # right account/company/code.  Note: the One2many is cached empty right
        # after create() until invalidated (it is populated lazily by _search),
        # so invalidate before reading it.
        acc = self.env["account.account"].create(
            {"code": "170000", "name": "Map", "account_type": "asset_current"}
        )
        acc.invalidate_recordset(["code_mapping_ids"])
        mapping = acc.code_mapping_ids
        self.assertTrue(mapping)
        self.assertEqual(
            mapping,
            self.env["account.code.mapping"].search([("account_id", "in", acc.ids)]),
        )
        for m in mapping:
            self.assertEqual(m.account_id, acc)
            self.assertIn(m.company_id, self.env.user.company_ids)
            self.assertEqual(m.code, acc.with_company(m.company_id).code)

    def test_pack_mapping_id_encoding(self):
        # The virtual id must round-trip (account_id, company_id) even for a
        # company id that would have overflowed the old 10**4 offset.
        from odoo.addons.base_account.models.account_code_mapping import (
            COMPANY_OFFSET,
            _pack_mapping_id,
        )

        account_id, company_id = 42, 10001
        vid = _pack_mapping_id(account_id, company_id)
        self.assertEqual(vid // COMPANY_OFFSET, account_id)
        self.assertEqual(vid % COMPANY_OFFSET, company_id)

    def test_pack_mapping_id_guards_overflow(self):
        from odoo.addons.base_account.models.account_code_mapping import (
            COMPANY_OFFSET,
            _pack_mapping_id,
        )

        with self.assertRaises(ValueError):
            _pack_mapping_id(1, COMPANY_OFFSET)
