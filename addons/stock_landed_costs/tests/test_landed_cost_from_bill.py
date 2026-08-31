from odoo import Command, fields
from odoo.tests import tagged

from .common import TestStockLandedCostsCommon


@tagged("post_install", "-at_install")
class TestLandedCostFromBill(TestStockLandedCostsCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.landed_cost.write(
            {
                "landed_cost_ok": True,
                "categ_id": cls.categ_all.id,
                "type": "service",
            }
        )
        cls.bill = cls.env["account.move"].create(
            {
                "move_type": "in_invoice",
                "partner_id": cls.supplier_id,
                "invoice_date": fields.Date.context_today(cls.env["account.move"]),
                "invoice_line_ids": [
                    Command.create(
                        {
                            "product_id": cls.landed_cost.id,
                            "quantity": 1,
                            "price_unit": 50.0,
                            "is_landed_costs_line": True,
                        }
                    ),
                ],
            }
        )

    def test_landed_costs_visible_before_creation(self):
        self.assertTrue(self.bill.landed_costs_visible)

    def test_button_create_landed_costs_mirrors_lines(self):
        action = self.bill.button_create_landed_costs()
        self.assertEqual(action["res_model"], "stock.landed.cost")
        landed_cost = self.env["stock.landed.cost"].browse(action["res_id"])
        self.assertEqual(landed_cost.vendor_bill_id, self.bill)
        self.assertEqual(len(landed_cost.cost_lines), 1)
        self.assertAlmostEqual(landed_cost.cost_lines.price_unit, 50.0, places=2)
        self.assertFalse(self.bill.landed_costs_visible)

    def test_action_view_landed_costs_single_form(self):
        self.bill.button_create_landed_costs()
        action = self.bill.action_view_landed_costs()
        self.assertEqual(action["res_model"], "stock.landed.cost")
        self.assertEqual(action["res_id"], self.bill.landed_costs_ids.id)
