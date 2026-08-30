"""Tests for the Vendor Bills section of project profitability."""

import json

from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestPurchaseItems(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids += cls.env.ref("project.group_project_manager")
        plan = cls.env["account.analytic.plan"].sudo().search([], limit=1)
        cls.analytic_account = cls.env["account.analytic.account"].create(
            {"name": "PA purchase account", "plan_id": plan.id}
        )
        cls.project = cls.env["project.project"].create(
            {"name": "PA purchase project", "account_id": cls.analytic_account.id}
        )

    def _in_invoice(self, price_unit, state="posted"):
        move = self.env["account.move"].create(
            {
                "move_type": "in_invoice",
                "partner_id": self.partner_a.id,
                "invoice_date": "2024-01-01",
                "invoice_line_ids": [
                    (
                        0,
                        0,
                        {
                            "product_id": self.product_a.id,
                            "price_unit": price_unit,
                            "quantity": 1,
                            "tax_ids": [(6, 0, [])],
                            "analytic_distribution": {
                                str(self.analytic_account.id): 100
                            },
                        },
                    )
                ],
            }
        )
        if state == "posted":
            move.action_post()
        return move

    def test_no_lines_yields_no_section(self):
        """Without vendor-bill lines, no 'Vendor Bills' section is added."""
        profitability_items = {
            "costs": {"data": [], "total": {"billed": 0.0, "to_bill": 0.0}}
        }
        self.project._add_purchase_items(profitability_items, with_action=False)
        self.assertEqual(profitability_items["costs"]["data"], [])
        self.assertEqual(profitability_items["costs"]["total"]["billed"], 0.0)
        self.assertEqual(profitability_items["costs"]["total"]["to_bill"], 0.0)

    def test_posted_bill_lands_in_billed(self):
        """A posted vendor bill's amount lands in 'billed', not 'to_bill'."""
        self._in_invoice(100.0, state="posted")
        profitability_items = {
            "costs": {"data": [], "total": {"billed": 0.0, "to_bill": 0.0}}
        }
        self.project._add_purchase_items(profitability_items, with_action=False)
        costs = profitability_items["costs"]
        self.assertEqual(costs["data"][0]["id"], "other_purchase_costs")
        self.assertEqual(costs["data"][0]["billed"], -100.0)
        self.assertEqual(costs["data"][0]["to_bill"], 0.0)
        self.assertEqual(costs["total"]["billed"], -100.0)
        self.assertEqual(costs["total"]["to_bill"], 0.0)

    def test_draft_bill_lands_in_to_bill(self):
        """A draft vendor bill's amount lands in 'to_bill', not 'billed'."""
        self._in_invoice(50.0, state="draft")
        profitability_items = {
            "costs": {"data": [], "total": {"billed": 0.0, "to_bill": 0.0}}
        }
        self.project._add_purchase_items(profitability_items, with_action=False)
        costs = profitability_items["costs"]
        self.assertEqual(costs["data"][0]["billed"], 0.0)
        self.assertEqual(costs["data"][0]["to_bill"], -50.0)
        self.assertEqual(costs["total"]["billed"], 0.0)
        self.assertEqual(costs["total"]["to_bill"], -50.0)

    def test_with_action_adds_action_key(self):
        """with_action=True adds an 'action' key to the section."""
        move = self._in_invoice(100.0, state="posted")
        profitability_items = {
            "costs": {"data": [], "total": {"billed": 0.0, "to_bill": 0.0}}
        }
        self.project._add_purchase_items(profitability_items, with_action=True)
        action = profitability_items["costs"]["data"][0]["action"]
        self.assertEqual(action["name"], "action_profitability_items")
        section_name, domain, res_id = json.loads(action["args"])
        self.assertEqual(section_name, "other_purchase_costs")
        self.assertEqual(domain, [["id", "in", [move.id]]])
        self.assertEqual(res_id, move.id)


@tagged("post_install", "-at_install")
class TestActionProfitabilityItems(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids += cls.env.ref("project.group_project_manager")
        plan = cls.env["account.analytic.plan"].sudo().search([], limit=1)
        cls.analytic_account = cls.env["account.analytic.account"].create(
            {"name": "PA action account", "plan_id": plan.id}
        )
        cls.project = cls.env["project.project"].create(
            {"name": "PA action project", "account_id": cls.analytic_account.id}
        )

    def test_other_purchase_costs_action(self):
        """action_profitability_items opens vendor bills for 'other_purchase_costs'."""
        action = self.project.action_profitability_items(
            "other_purchase_costs", domain=[]
        )
        self.assertEqual(action["domain"], [])
        self.assertFalse(action["res_id"])

    def test_other_purchase_costs_action_with_res_id(self):
        """Passing a res_id switches the action to a single-record form view."""
        action = self.project.action_profitability_items(
            "other_purchase_costs", domain=[], res_id=42
        )
        self.assertEqual(action["res_id"], 42)
        self.assertEqual(action["view_mode"], "form")
        self.assertEqual(action["views"], [(False, "form")])

    def test_other_revenues_aal_action(self):
        """action_profitability_items opens the AAL entries pivot/graph for AAL sections."""
        action = self.project.action_profitability_items(
            "other_revenues_aal", domain=[("id", "in", [])]
        )
        self.assertEqual(action["domain"], [("id", "in", [])])
        view_types = [view_type for _view_id, view_type in action["views"]]
        self.assertIn("pivot", view_types)
        self.assertIn("graph", view_types)

    def test_action_view_analytic_items(self):
        """action_view_analytic_items opens all analytic lines of the project's account."""
        action = self.project.action_view_analytic_items()
        self.assertEqual(
            action["domain"], [("account_id", "=", self.analytic_account.id)]
        )
        self.assertEqual(
            action["context"]["default_account_id"], self.analytic_account.id
        )
