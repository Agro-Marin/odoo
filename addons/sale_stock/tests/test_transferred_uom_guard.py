# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.sale_stock.tests.common import TestSaleStockCommon


@tagged("post_install", "-at_install")
class TestTransferredUomGuard(TestSaleStockCommon):
    """Posting-boundary guard for the leniently-computed transferred qty.

    ``qty_transferred`` converts delivery moves into the order-line UoM through
    ``_compute_quantity_reconcile``, which degrades (returns the quantity
    unconverted) instead of raising on incompatible units, so an order carrying
    legacy incompatible-UoM data stays browsable.  That degraded quantity must
    never silently size an invoice line: creating the invoice must fail loud.
    """

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
        # A UoM in an unrelated category (Working Time), so it shares no common
        # reference with the product's Units UoM.
        cls.uom_incompatible = cls.env.ref("uom.product_uom_hour")

    def test_incompatible_transferred_uom_blocks_invoicing(self):
        so = self._so_deliver(self.product_delivered, quantity=5)
        line = so.line_ids.filtered(lambda l: l.product_id == self.product_delivered)
        self.assertEqual(line.qty_transferred, 5)

        # Simulate legacy corruption: a delivered move recorded in a UoM that
        # cannot be converted to the order-line UoM. The ORM forbids changing a
        # done move's UoM, so write at the SQL level to reproduce data that
        # predates that guard.
        done_move = so.picking_ids.move_ids.filtered(lambda m: m.state == "done")
        self.env.cr.execute(
            "UPDATE stock_move SET product_uom_id = %s WHERE id = %s",
            (self.uom_incompatible.id, done_move.id),
        )
        self.env.invalidate_all()

        # Browsing still works: the stored compute degrades instead of raising.
        line.invalidate_recordset(["qty_transferred"])
        self.assertEqual(
            line.qty_transferred,
            done_move.quantity,
            "Incompatible UoM must degrade (unconverted) while browsing, not raise",
        )

        # Posting boundary: creating the invoice re-validates strictly and
        # refuses to size the invoice on the unconverted quantity.
        with self.assertRaises(UserError):
            so._create_invoices()

    def test_compatible_transferred_uom_still_invoices(self):
        """The guard is inert when the delivery UoM is convertible: an ordinary
        delivered invoice is created without interference."""
        so = self._so_deliver(self.product_delivered, quantity=3)
        invoice = so._create_invoices()
        self.assertTrue(invoice)
        self.assertEqual(invoice.invoice_line_ids.quantity, 3)
