from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.sale_stock.tests.common import TestSaleStockCommon


@tagged("post_install", "-at_install")
class TestTransferredUomGuard(TestSaleStockCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.env.company.id)], limit=1
        )
        cls.owner = cls.partner_a
        cls.product_delivered = cls.env["product.product"].create(
            {
                "name": "Guarded delivered product",
                "is_storable": True,
                "invoice_policy": "transferred",
                "uom_id": cls.env.ref("uom.product_uom_unit").id,
            }
        )
        cls.uom_incompatible = cls.env.ref("uom.product_uom_hour")

    def test_incompatible_transferred_uom_blocks_invoicing(self):
        so = self._so_deliver(self.product_delivered, quantity=5)
        line = so.line_ids.filtered(lambda l: l.product_id == self.product_delivered)
        self.assertEqual(line.qty_transferred, 5)

        done_move = so.picking_ids.move_ids.filtered(lambda m: m.state == "done")
        self.env.cr.execute(
            "UPDATE stock_move SET product_uom_id = %s WHERE id = %s",
            (self.uom_incompatible.id, done_move.id),
        )
        self.env.invalidate_all()

        line.invalidate_recordset(["qty_transferred"])
        self.assertEqual(
            line.qty_transferred,
            done_move.quantity,
            "Incompatible UoM must degrade (unconverted) while browsing, not raise",
        )

        with self.assertRaises(UserError):
            so._create_invoices()

    def test_compatible_transferred_uom_still_invoices(self):
        so = self._so_deliver(self.product_delivered, quantity=3)
        invoice = so._create_invoices()
        self.assertTrue(invoice)
        self.assertEqual(invoice.invoice_line_ids.quantity, 3)
