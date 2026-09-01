from odoo.tests import tagged

from odoo.addons.l10n_mx.tests.common import TestMxCommon


@tagged("post_install_l10n", "post_install", "-at_install")
class TestMxChartTemplate(TestMxCommon):
    """What a company created on the `mx` template actually gets."""

    def _account(self, code):
        return (
            self.env["account.account"]
            .with_company(self.company_data["company"])
            .search([("code", "=", code)])
        )

    def test_the_fixed_asset_block_is_created(self):
        """The SAT fixed-asset accounts, their accumulated depreciation and the
        matching depreciation expense accounts."""
        expected = {
            "153.01.01": "asset_fixed",  # Machinery & equipment
            "154.01.01": "asset_fixed",  # Vehicles
            "155.01.01": "asset_fixed",  # Furniture & office equipment
            "156.01.01": "asset_fixed",  # Technology
            "171.02.01": "asset_fixed",  # Acc. depreciation, machinery
            "171.03.01": "asset_fixed",  # Acc. depreciation, vehicles
            "183.01.01": "asset_non_current",  # Acc. amortization, deferred
            "613.02.01": "expense_direct_cost",  # Depreciation, machinery
            "614.01.01": "expense_direct_cost",  # Amortization, deferred
        }
        for code, account_type in expected.items():
            account = self._account(code)
            self.assertTrue(account, f"account {code} is missing from the MX chart")
            self.assertEqual(
                account.account_type,
                account_type,
                f"account {code} has the wrong type",
            )

    def test_accounts_carry_their_description(self):
        """The template now explains what each account is for.

        `description` is declared by account_coa (models/account_account.py:32)
        and reaches l10n_mx because account depends on account_coa. This
        account already existed; what is new is the text on it.
        """
        stock_valuation = self._account("115.01.01")
        self.assertTrue(stock_valuation)
        self.assertEqual(
            stock_valuation.description,
            "Goods stored in your warehouse, as part of your activity",
        )

    def test_the_depreciation_models_are_created(self):
        """Only reachable where asset management is installed: account.asset
        lives in enterprise, and the template CSV is skipped without it."""
        if "account.asset" not in self.env:
            self.skipTest("account_asset is not installed")
        models = (
            self.env["account.asset"]
            .with_company(self.company_data["company"])
            .search([("state", "=", "model")])
        )
        self.assertEqual(len(models), 9)
