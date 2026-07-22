"""Tests for the Materials line of project profitability (picking AALs)."""

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestProfitabilityMaterials(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        plan = cls.env["account.analytic.plan"].sudo().search([], limit=1)
        cls.analytic_account = cls.env["account.analytic.account"].create(
            {"name": "PSA materials account", "plan_id": plan.id}
        )
        cls.project = cls.env["project.project"].create(
            {"name": "PSA project", "account_id": cls.analytic_account.id}
        )

    def _picking_aal(self, amount):
        return self.env["account.analytic.line"].create(
            {
                "name": "PSA picking cost",
                "account_id": self.analytic_account.id,
                "amount": amount,
                "category": "picking_entry",
            }
        )

    def test_no_picking_aal_returns_false(self):
        """Without picking analytic lines there is no Materials section."""
        self.assertFalse(self.project._get_items_from_aal_picking(with_action=False))

    def test_picking_aal_sums_into_materials_costs(self):
        """Picking analytic lines aggregate into the other_costs item."""
        self._picking_aal(-75.0)
        self._picking_aal(-25.0)
        items = self.project._get_items_from_aal_picking(with_action=False)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], "other_costs")
        self.assertEqual(items[0]["billed"], -100.0)
        self.assertEqual(items[0]["to_bill"], 0.0)

    def test_materials_costs_merge_into_profitability(self):
        """The Materials total lands in the project profitability costs."""
        self._picking_aal(-40.0)
        items = self.project._get_profitability_items(with_action=False)
        materials = [
            item for item in items["costs"]["data"] if item["id"] == "other_costs"
        ]
        self.assertEqual(len(materials), 1)
        self.assertEqual(materials[0]["billed"], -40.0)

    def test_materials_label_registered(self):
        """The other_costs label is exposed for the profitability report."""
        self.assertIn("other_costs", self.project._get_profitability_labels())
