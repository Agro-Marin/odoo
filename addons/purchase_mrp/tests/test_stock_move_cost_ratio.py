"""Tests for the phantom-BoM cost-ratio math on ``stock.move``.

The bill-valuation flows of this module (anglo-saxon entries) need the
accounting stack and a chart-template load that production-clone test
databases cannot perform; the cost-share arithmetic underneath them is
testable directly on moves and is pinned here.
"""

from odoo import Command
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestStockMoveCostRatio(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.uom_unit = cls.env.ref("uom.product_uom_unit")
        cls.kit = cls.env["product.product"].create(
            {"name": "PMRP kit", "type": "consu", "uom_id": cls.uom_unit.id}
        )
        cls.component = cls.env["product.product"].create(
            {"name": "PMRP component", "type": "consu", "uom_id": cls.uom_unit.id}
        )
        cls.phantom_bom = cls.env["mrp.bom"].create(
            {
                "product_tmpl_id": cls.kit.product_tmpl_id.id,
                "type": "phantom",
                "product_qty": 1.0,
                "bom_line_ids": [
                    Command.create({"product_id": cls.component.id, "product_qty": 2.0})
                ],
            }
        )
        cls.stock_location = cls.env.ref("stock.stock_location_stock")
        cls.supplier_location = cls.env.ref("stock.stock_location_suppliers")

    def _move(self, quantity, bom_line=None, cost_share=0.0):
        return self.env["stock.move"].create(
            {
                "product_id": self.component.id,
                "product_uom_id": self.uom_unit.id,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
                "quantity": quantity,
                "bom_line_id": bom_line.id if bom_line else False,
                "cost_share": cost_share,
            }
        )

    def test_cost_ratio_phantom_applies_cost_share(self):
        """Phantom components weigh cost_share and partial quantity."""
        move = self._move(4.0, bom_line=self.phantom_bom.bom_line_ids, cost_share=50.0)
        # (cost_share/100) * (qty / uom_qty) * unit_kit_purchase
        # = 0.5 * (2/4) * 1 = 0.25
        self.assertEqual(move._get_cost_ratio(2.0), 0.25)

    def test_cost_ratio_full_quantity_is_cost_share(self):
        """Taking the whole move quantity leaves exactly the cost share."""
        move = self._move(4.0, bom_line=self.phantom_bom.bom_line_ids, cost_share=30.0)
        self.assertEqual(move._get_cost_ratio(4.0), 0.30)

    def test_cost_ratio_zero_quantity_falls_back(self):
        """A zero-quantity move cannot use the phantom math (boundary)."""
        move = self._move(0.0, bom_line=self.phantom_bom.bom_line_ids, cost_share=50.0)
        twin = self._move(0.0)
        self.assertEqual(move._get_cost_ratio(1.0), twin._get_cost_ratio(1.0))

    def test_cost_ratio_without_phantom_delegates(self):
        """Moves outside a phantom kit keep the standard ratio (boundary)."""
        move = self._move(4.0, cost_share=50.0)
        twin = self._move(4.0)
        self.assertEqual(move._get_cost_ratio(2.0), twin._get_cost_ratio(2.0))
