"""Tests for the analytic-line split of project profitability."""

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestProfitabilityAal(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        plan = cls.env["account.analytic.plan"].sudo().search([], limit=1)
        cls.analytic_account = cls.env["account.analytic.account"].create(
            {"name": "PA profitability account", "plan_id": plan.id}
        )
        cls.project = cls.env["project.project"].create(
            {"name": "PA project", "account_id": cls.analytic_account.id}
        )

    def _aal(self, amount, category=False):
        values = {
            "name": "PA line",
            "account_id": self.analytic_account.id,
            "amount": amount,
        }
        if category:
            values["category"] = category
        return self.env["account.analytic.line"].create(values)

    def test_no_lines_yields_zero_totals(self):
        """Without analytic lines both sections come back empty (boundary)."""
        items = self.project._get_items_from_aal(with_action=False)
        self.assertEqual(items["revenues"]["total"]["invoiced"], 0.0)
        self.assertEqual(items["costs"]["total"]["billed"], 0.0)

    def test_lines_split_by_sign(self):
        """Positive amounts land in revenues, negative in costs."""
        self._aal(120.0)
        self._aal(-45.0)
        self._aal(-5.0)
        items = self.project._get_items_from_aal(with_action=False)
        self.assertEqual(items["revenues"]["total"]["invoiced"], 120.0)
        self.assertEqual(items["costs"]["total"]["billed"], -50.0)
        self.assertEqual(items["revenues"]["data"][0]["id"], "other_revenues_aal")
        self.assertEqual(items["costs"]["data"][0]["id"], "other_costs_aal")

    def test_stock_categories_excluded(self):
        """Manufacturing/picking lines belong to other sections (boundary)."""
        self._aal(-80.0, category="picking_entry")
        self._aal(-70.0, category="manufacturing_order")
        items = self.project._get_items_from_aal(with_action=False)
        self.assertEqual(items["costs"]["total"]["billed"], 0.0)

    def test_to_bill_and_to_invoice_stay_zero(self):
        """AAL amounts cannot be split by billing state: to_* stay at 0."""
        self._aal(200.0)
        self._aal(-10.0)
        items = self.project._get_items_from_aal(with_action=False)
        self.assertEqual(items["revenues"]["data"][0]["to_invoice"], 0.0)
        self.assertEqual(items["costs"]["data"][0]["to_bill"], 0.0)
