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


@tagged("post_install", "-at_install")
class TestLandedCostFromPurchaseBill(TestStockLandedCostsCommon):
    """A landed cost created from a vendor bill knows its own transfers.

    The bill already carries the purchase order it was built from, and the
    purchase order already carries the receipts. Making the user search for
    and pick those receipts by hand on the landed cost form is a step the
    record has all the information to take by itself.
    """

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

    @classmethod
    def _confirmed_order(cls, product, quantity=5, price_unit=10.0):
        order = cls.env["purchase.order"].create(
            {
                "partner_id": cls.supplier_id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": product.id,
                            "product_qty": quantity,
                            "price_unit": price_unit,
                        }
                    ),
                ],
            }
        )
        order.action_confirm()
        return order

    @classmethod
    def _receive(cls, order):
        receipt = order.picking_ids
        receipt.move_ids.quantity = sum(order.line_ids.mapped("product_qty"))
        receipt.move_ids.picked = True
        receipt.button_validate()
        return receipt

    @classmethod
    def _bill_with_a_landed_cost_line(cls, order):
        order.create_invoice()
        bill = order.invoice_ids
        bill.invoice_date = fields.Date.context_today(bill)
        bill.write(
            {
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
        bill.action_post()
        return bill

    def test_a_bill_prefills_the_transfers_of_its_purchase_order(self):
        order = self._confirmed_order(self.product_refrigerator)
        receipt = self._receive(order)
        bill = self._bill_with_a_landed_cost_line(order)

        action = bill.button_create_landed_costs()
        landed_cost = self.env[action["res_model"]].browse(action["res_id"])

        self.assertEqual(
            landed_cost.picking_ids.ids,
            receipt.ids,
            "the receipt of the bill's purchase order should already be there",
        )

    def test_a_transfer_with_nothing_valued_is_left_out(self):
        order = self._confirmed_order(self.product_refrigerator)
        bill = self._bill_with_a_landed_cost_line(order)
        self.assertTrue(order.picking_ids, "fixture: the order must have a receipt")
        self.assertFalse(
            order.picking_ids.move_ids.filtered("is_valued"),
            "fixture: an unvalidated receipt values nothing",
        )

        action = bill.button_create_landed_costs()
        landed_cost = self.env[action["res_model"]].browse(action["res_id"])

        self.assertFalse(
            landed_cost.picking_ids,
            "a receipt that valued nothing has no landed cost to carry",
        )

    def test_a_bill_without_a_purchase_order_prefills_nothing(self):
        bill = self.env["account.move"].create(
            {
                "move_type": "in_invoice",
                "partner_id": self.supplier_id,
                "invoice_date": fields.Date.context_today(self.env["account.move"]),
                "invoice_line_ids": [
                    Command.create(
                        {
                            "product_id": self.landed_cost.id,
                            "quantity": 1,
                            "price_unit": 50.0,
                            "is_landed_costs_line": True,
                        }
                    ),
                ],
            }
        )
        bill.action_post()

        action = bill.button_create_landed_costs()
        landed_cost = self.env[action["res_model"]].browse(action["res_id"])

        self.assertFalse(landed_cost.picking_ids)
        self.assertEqual(landed_cost.vendor_bill_id, bill)
