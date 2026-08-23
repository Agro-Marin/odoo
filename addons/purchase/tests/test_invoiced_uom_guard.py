from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("-at_install", "post_install")
class TestInvoicedUomGuard(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.uom_unit = cls.env.ref("uom.product_uom_unit")
        cls.uom_incompatible = cls.env.ref("uom.product_uom_hour")
        cls.product = cls.env["product.product"].create(
            {
                "name": "Guarded billed product",
                "type": "service",
                "bill_policy": "ordered",
                "purchase_ok": True,
                "standard_price": 100.0,
                "uom_id": cls.uom_unit.id,
                "supplier_taxes_id": [Command.clear()],
            },
        )

    def _confirmed_po(self, qty=10):
        po = self.env["purchase.order"].create(
            {
                "partner_id": self.partner_a.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product.id,
                            "product_qty": qty,
                            "price_unit": 100,
                            "tax_ids": [Command.clear()],
                        },
                    ),
                ],
            },
        )
        po.action_confirm()
        return po

    def _post_partial_bill(self, po, qty):
        bill = po.create_invoice()
        bill.invoice_date = "2026-01-01"
        bill.invoice_line_ids.quantity = qty
        bill.action_post()
        return bill

    def _corrupt_bill_line_uom(self, bill):
        self.env.cr.execute(
            "UPDATE account_move_line SET product_uom_id = %s WHERE id = %s",
            (self.uom_incompatible.id, bill.invoice_line_ids.id),
        )
        self.env.invalidate_all()

    def test_fixture_uoms_share_no_reference(self):
        self.assertFalse(self.uom_unit._has_common_reference(self.uom_incompatible))

    def test_incompatible_invoiced_uom_degrades_while_browsing(self):
        po = self._confirmed_po()
        bill = self._post_partial_bill(po, 4)
        self.assertEqual(po.line_ids.qty_invoiced, 4)

        self._corrupt_bill_line_uom(bill)
        po.line_ids.invalidate_recordset(["qty_invoiced"])
        self.assertEqual(
            po.line_ids.qty_invoiced,
            4,
            "Incompatible UoM must degrade (unconverted) while browsing, not raise",
        )

    def test_incompatible_invoiced_uom_blocks_further_billing(self):
        po = self._confirmed_po()
        bill = self._post_partial_bill(po, 4)
        self._corrupt_bill_line_uom(bill)

        with self.assertRaises(UserError):
            po.create_invoice()

    def test_incompatible_invoiced_uom_blocks_bill_matching(self):
        po = self._confirmed_po()
        bill = self._post_partial_bill(po, 4)
        self._corrupt_bill_line_uom(bill)

        new_bill = self.env["account.move"].create(
            {"move_type": "in_invoice", "partner_id": self.partner_a.id},
        )
        with self.assertRaises(UserError):
            new_bill._add_order_lines(po.line_ids)

    def test_compatible_invoiced_uom_still_bills(self):
        po = self._confirmed_po()
        self._post_partial_bill(po, 4)

        bill = po.create_invoice()
        self.assertTrue(bill)
        self.assertEqual(bill.invoice_line_ids.quantity, 6)
