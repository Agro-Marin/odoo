from lxml.etree import fromstring

from odoo.tests import tagged

from odoo.addons.stock_account.tests.common import TestStockValuationCommon


@tagged("post_install", "-at_install")
class TestArchivedValuationAccounts(TestStockValuationCommon):
    """Archiving an account that a valuation field still points at is not
    cosmetic: `account.move._post` refuses the entry with "A line of this move
    is using a archived account, you cannot post it", so the valuation closing
    stops working with no clue as to which field is at fault. Flag the dead
    account on the form that configures it.
    """

    def _arch(self, model, xmlid):
        return fromstring(
            self.env[model].get_view(view_id=self.env.ref(xmlid).id)["arch"]
        )

    def test_category_valuation_account_reports_its_active_flag(self):
        category = self.category_avco_auto
        account = self.account_stock_valuation
        category.property_stock_valuation_account_id = account
        self.assertTrue(
            category.property_stock_valuation_account_active,
            "a live valuation account must not be flagged",
        )

        account.action_archive()
        category.invalidate_recordset(["property_stock_valuation_account_active"])
        self.assertFalse(
            category.property_stock_valuation_account_active,
            "archiving the account must show through on the category",
        )

    def test_account_stock_variation_reports_its_active_flag(self):
        account = self.account_stock_valuation
        variation = self.account_stock_variation
        self.assertTrue(variation, "the fixture wires a variation account")
        self.assertTrue(account.account_stock_variation_active)

        variation.action_archive()
        account.invalidate_recordset(["account_stock_variation_active"])
        self.assertFalse(account.account_stock_variation_active)

    def test_category_form_mutes_archived_accounts(self):
        arch = self._arch("product.category", "account.view_category_property_form")
        for fname, flag in (
            (
                "property_stock_valuation_account_id",
                "property_stock_valuation_account_active",
            ),
            ("account_stock_variation_id", "account_stock_variation_active"),
            (
                "property_price_difference_account_id",
                "property_price_difference_account_active",
            ),
        ):
            node = arch.find(f".//field[@name='{fname}']")
            self.assertIsNotNone(node, f"{fname} must stay on the category form")
            self.assertEqual(node.get("decoration-muted"), f"not {flag}")

    def test_account_form_mutes_archived_stock_accounts(self):
        arch = self._arch("account.account", "account.view_account_form")
        for fname, flag in (
            ("account_stock_variation_id", "account_stock_variation_active"),
            ("account_stock_expense_id", "account_stock_expense_active"),
        ):
            node = arch.find(f".//field[@name='{fname}']")
            self.assertIsNotNone(node, f"{fname} must stay on the account form")
            self.assertEqual(node.get("decoration-muted"), f"not {flag}")
