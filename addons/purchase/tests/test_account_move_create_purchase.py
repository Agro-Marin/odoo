from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestCreatePurchaseOrder(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.env.user.group_ids += cls.env.ref("purchase.group_purchase_user")

        cls.vendor = cls.env["res.partner"].create(
            {
                "name": "Test Vendor",
                "supplier_rank": 1,
            }
        )

        cls.product_purchasable = cls.env["product.product"].create(
            {
                "name": "Purchasable Product",
                "type": "consu",
                "purchase_ok": True,
            }
        )

    def _create_bill(self, line_vals):
        return self.env["account.move"].create(
            {
                "move_type": "in_invoice",
                "partner_id": self.vendor.id,
                "invoice_date": fields.Date.context_today(self.env.user),
                "invoice_line_ids": [(0, 0, line_vals)],
            }
        )

    def test_create_purchase_order_success(self):
        bill = self._create_bill(
            {
                "product_id": self.product_purchasable.id,
                "quantity": 5,
                "price_unit": 50.0,
            }
        )
        bill.action_post()

        result = bill.create_purchase_order()

        self.assertTrue(result, "Should return True on success")

        po = self.env["purchase.order"].search(
            [
                ("partner_id", "=", self.vendor.id),
                ("origin", "=", bill.name),
            ],
            limit=1,
        )

        self.assertTrue(po, "Purchase order should be created")
        self.assertEqual(po.partner_id, self.vendor, "PO should have correct vendor")
        self.assertEqual(len(po.line_ids), 1, "PO should have one line")
        self.assertEqual(
            po.line_ids.product_id,
            self.product_purchasable,
            "PO line should have correct product",
        )
        self.assertEqual(
            bill.invoice_line_ids.purchase_line_ids,
            po.line_ids,
            "The move line should be linked to the created PO line",
        )

    def test_create_purchase_order_no_product_error(self):
        bill = self._create_bill(
            {
                "name": "Service without product",
                "quantity": 1,
                "price_unit": 100.0,
            }
        )

        with self.assertRaises(UserError) as context:
            bill.create_purchase_order()

        self.assertIn(
            "product",
            str(context.exception).lower(),
            "Error should mention missing product",
        )

    def test_create_purchase_order_idempotent_when_one_exists(self):
        bill = self._create_bill(
            {
                "product_id": self.product_purchasable.id,
                "quantity": 5,
                "price_unit": 50.0,
            }
        )
        bill.action_post()

        bill.create_purchase_order()

        bill.create_purchase_order()

        pos = self.env["purchase.order"].search(
            [
                ("partner_id", "=", self.vendor.id),
                ("origin", "=", bill.name),
            ],
        )
        self.assertEqual(
            len(pos),
            1,
            "Second create_purchase_order call must not duplicate the PO",
        )

    def test_create_purchase_order_raises_when_duplicates_exist(self):
        bill = self._create_bill(
            {
                "product_id": self.product_purchasable.id,
                "quantity": 5,
                "price_unit": 50.0,
            }
        )
        bill.action_post()

        for _dummy in range(2):
            self.env["purchase.order"].create(
                {
                    "partner_id": self.vendor.id,
                    "origin": bill.name,
                },
            )

        with self.assertRaises(UserError) as context:
            bill.create_purchase_order()

        self.assertIn(
            "more than one",
            str(context.exception).lower(),
            "Error should mention the multiple-PO condition",
        )
