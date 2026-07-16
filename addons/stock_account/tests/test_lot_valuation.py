# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.exceptions import UserError

from odoo.addons.stock_account.tests.common import TestStockValuationCommon


class TestLotValuationCommon(TestStockValuationCommon):
    """Fixtures for the fork's lot-valuation engine (AVCO valued per lot).

    The previous suite here was an unadapted copy of upstream's
    ``stock.valuation.layer`` tests (skipped, and referencing removed API). This
    replacement exercises the real fork API — ``product.value`` history plus the
    ``total_value``/``standard_price``/``product_qty`` computes — while keeping the
    known-correct value expectations from the upstream scenarios.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.category_avco.property_cost_method = "average"
        cls.product1 = cls.env["product.product"].create(
            {
                "name": "Lot AVCO Product",
                "is_storable": True,
                "tracking": "lot",
                "categ_id": cls.category_avco.id,
                "standard_price": 0.0,
            }
        )
        cls.product1.product_tmpl_id.lot_valuated = True
        cls.lot1, cls.lot2, cls.lot3 = cls.env["stock.lot"].create(
            [
                {"name": "lot1", "product_id": cls.product1.id},
                {"name": "lot2", "product_id": cls.product1.id},
                {"name": "lot3", "product_id": cls.product1.id},
            ]
        )

    def _internal_quant(self, lot):
        return lot.quant_ids.filtered(lambda q: q.location_id.usage == "internal")


class TestLotValuation(TestLotValuationCommon):
    def test_lot_normal_1(self):
        """Each lot carries its own cost; an out move on a cheaper lot recomputes
        the product's average cost."""
        self._make_in_move(self.product1, 10, 5, lot_ids=[self.lot1, self.lot2])
        self._make_in_move(self.product1, 10, 7, lot_ids=[self.lot3])
        # standard_price is stored at the 'Product Price' precision (2 dp), so assert
        # the precise invariant on total_value / qty and keep standard_price at 2 dp.
        self.assertEqual(self.product1.total_value, 120)
        self.assertEqual(self.product1.qty_available, 20)
        self.assertEqual(self.lot1.standard_price, 5)
        self.assertEqual(self.lot3.standard_price, 7)

        self._make_out_move(self.product1, 2, lot_ids=[self.lot1])

        # lot1 is cheaper than the product average, so shipping it lifts the average.
        self.assertEqual(self.product1.total_value, 110)  # 15 + 25 + 70
        self.assertEqual(self.product1.qty_available, 18)
        self.assertAlmostEqual(self.product1.standard_price, 6.11, places=2)
        self.assertEqual(self.lot1.total_value, 15)
        self.assertEqual(self.lot1.product_qty, 3)
        self.assertEqual(self.lot1.standard_price, 5)
        self.assertEqual(self._internal_quant(self.lot1).value, 15)
        self.assertEqual(self.lot2.total_value, 25)
        self.assertEqual(self.lot2.product_qty, 5)
        self.assertEqual(self._internal_quant(self.lot2).value, 25)
        self.assertEqual(self.lot3.total_value, 70)
        self.assertEqual(self.lot3.product_qty, 10)
        self.assertEqual(self._internal_quant(self.lot3).value, 70)

    def test_oversold_lot_fallback(self):
        """Delivering a lot that has no cost basis of its own (never received, hence
        oversold) values the move AND the resulting inventory at the product's average
        cost, not at 0.

        Regression for two coupled defects:
        - ``stock.move._set_value`` valued the out move at 0 (understated COGS);
        - the spurious ``0 -> 0`` ``product.value`` row created for 0-priced products
          seeded ``_run_average_batch`` with cost 0, leaving the product value
          overstated (50 / avg 6.25 instead of 40 / avg 5.0)."""
        self._make_in_move(self.product1, 10, 5, lot_ids=[self.lot1, self.lot2])
        out_move = self._make_out_move(self.product1, 2, lot_ids=[self.lot3])

        # lot3 was never received; the out must be valued at the product's cost (5).
        self.assertEqual(out_move.value, 10)
        # The 8 remaining units all cost 5, so the product value/average stay coherent.
        self.assertEqual(self.product1.total_value, 40)
        self.assertEqual(self.product1.qty_available, 8)
        self.assertAlmostEqual(self.product1.standard_price, 5.0, places=2)
        self.assertEqual(self.lot3.total_value, -10)
        self.assertEqual(self.lot3.product_qty, -2)

    def test_change_lot_cost(self):
        """Manually changing a lot's cost re-values that lot and the product cost,
        leaving the other lots untouched."""
        self._make_in_move(self.product1, 10, 5, lot_ids=[self.lot1, self.lot2])
        self._make_in_move(self.product1, 10, 7, lot_ids=[self.lot3])
        self._make_out_move(self.product1, 2, lot_ids=[self.lot1])

        self.lot1.standard_price = 10
        self.assertEqual(self.lot1.total_value, 30)
        self.assertEqual(self.lot1.product_qty, 3)
        self.assertEqual(self.lot1.standard_price, 10)
        # product total = 30 + 25 + 70 = 125 over 18 units (avg 6.9444, stored 6.94).
        self.assertEqual(self.product1.total_value, 125)
        self.assertEqual(self.product1.qty_available, 18)
        self.assertAlmostEqual(self.product1.standard_price, 6.94, places=2)
        # rest remains unchanged
        self.assertEqual(self.lot2.total_value, 25)
        self.assertEqual(self.lot2.standard_price, 5)
        self.assertEqual(self.lot3.total_value, 70)
        self.assertEqual(self.lot3.standard_price, 7)

    def test_change_standard_price_reevaluates_lots(self):
        """Setting the product standard price re-values every lot to that price."""
        self._make_in_move(self.product1, 10, 5, lot_ids=[self.lot1, self.lot2])
        self._make_in_move(self.product1, 8, 7, lot_ids=[self.lot3])
        self._make_in_move(self.product1, 6, 8, lot_ids=[self.lot2, self.lot3])
        self.assertEqual(self.lot1.total_value, 25)
        self.assertEqual(self.lot2.total_value, 49)
        self.assertEqual(self.lot3.total_value, 80)

        self.product1.product_tmpl_id.standard_price = 10

        self.assertEqual(self.lot1.standard_price, 10)
        self.assertEqual(self.lot1.total_value, 50)
        self.assertEqual(self.lot2.standard_price, 10)
        self.assertEqual(self.lot2.total_value, 80)
        self.assertEqual(self.lot3.standard_price, 10)
        self.assertEqual(self.lot3.total_value, 110)

    def test_enforce_lot_receipt(self):
        """A lot/serial number is mandatory on receipt for a lot-valuated product."""
        with self.assertRaises(UserError):
            self._make_in_move(self.product1, 10, 5)

    def test_enforce_lot_inventory(self):
        """A lot/serial number is mandatory when valuing an inventory adjustment."""
        inventory_quant = self.env["stock.quant"].create(
            {
                "location_id": self.stock_location.id,
                "product_id": self.product1.id,
                "inventory_quantity": 10,
            }
        )
        with self.assertRaises(UserError):
            inventory_quant.action_apply_inventory()

    def test_inventory_adjustment_takes_lot_cost(self):
        """An inventory adjustment on an existing lot is valued at that lot's cost."""
        self._make_in_move(self.product1, 10, 5, lot_ids=[self.lot1])
        shelf = self.env["stock.location"].create(
            {
                "name": "Shelf 1",
                "usage": "internal",
                "location_id": self.stock_location.id,
            }
        )
        inventory_quant = self.env["stock.quant"].create(
            {
                "location_id": shelf.id,
                "product_id": self.product1.id,
                "lot_id": self.lot1.id,
                "inventory_quantity": 1,
            }
        )
        inventory_quant.action_apply_inventory()
        self.assertEqual(self.lot1.standard_price, 5)
        self.assertEqual(self.lot1.product_qty, 11)
        self.assertEqual(self.lot1.total_value, 55)

    def test_inventory_adjustment_new_lot_takes_product_cost(self):
        """An inventory adjustment on a brand-new lot falls back to the product cost."""
        self._make_in_move(self.product1, 10, 5, lot_ids=[self.lot1])
        self._make_in_move(self.product1, 10, 9, lot_ids=[self.lot2])
        self.assertAlmostEqual(self.product1.standard_price, 7)
        lot4 = self.env["stock.lot"].create(
            {"name": "lot4", "product_id": self.product1.id}
        )
        shelf = self.env["stock.location"].create(
            {
                "name": "Shelf 1",
                "usage": "internal",
                "location_id": self.stock_location.id,
            }
        )
        inventory_quant = self.env["stock.quant"].create(
            {
                "location_id": shelf.id,
                "product_id": self.product1.id,
                "lot_id": lot4.id,
                "inventory_quantity": 1,
            }
        )
        inventory_quant.action_apply_inventory()
        self.assertEqual(lot4.standard_price, 7)
        self.assertEqual(lot4.total_value, 7)


class TestLotValuationRealTime(TestLotValuationCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product1.categ_id.property_valuation = "real_time"

    def test_realtime_valuation_is_consistent(self):
        """Switching a lot-valuated product to perpetual valuation must not change the
        computed lot/product value."""
        self._make_in_move(self.product1, 10, 5, lot_ids=[self.lot1, self.lot2])
        self._make_in_move(self.product1, 10, 7, lot_ids=[self.lot3])
        self._make_out_move(self.product1, 2, lot_ids=[self.lot1])

        # 20 received (50 + 70) minus 2 shipped from lot1 @5 = 110.
        self.assertEqual(self.product1.total_value, 110)
        self.assertEqual(self.lot1.total_value, 15)
        self.assertEqual(self.lot3.total_value, 70)


class TestLotStandardPriceHistory(TestStockValuationCommon):
    """Regression coverage for manual edits of a lot's standard price.

    Exercises the real fork API (``product.value`` history) to lock down
    ``stock.lot._change_standard_price``, which previously compared/formatted the
    whole ``{lot: price}`` mapping instead of the per-lot price.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.category_avco.property_cost_method = "average"
        cls.lot_product = cls.env["product.product"].create(
            {
                "name": "Lot Valued Product",
                "is_storable": True,
                "tracking": "lot",
                "categ_id": cls.category_avco.id,
                "standard_price": 10.0,
            }
        )
        cls.lot_product.product_tmpl_id.lot_valuated = True
        cls.lot = cls.env["stock.lot"].create(
            {
                "name": "LOT-REG",
                "product_id": cls.lot_product.id,
            }
        )

    def _lot_value_rows(self):
        return self.env["product.value"].search([("lot_id", "=", self.lot.id)])

    def test_noop_price_write_creates_no_history(self):
        """Writing the same standard price must not create a product.value row."""
        before = len(self._lot_value_rows())
        self.lot.standard_price = self.lot.standard_price
        self.assertEqual(
            len(self._lot_value_rows()),
            before,
            "A no-op standard_price write must not record a price-history row.",
        )

    def test_real_price_change_records_readable_history(self):
        """A real price change records one row whose description shows the prices."""
        before = len(self._lot_value_rows())
        self.lot.standard_price = 25.0
        rows = self._lot_value_rows()
        self.assertEqual(len(rows), before + 1)
        latest = rows.sorted("id")[-1]
        self.assertEqual(latest.value, 25.0)
        # The old price must be rendered as a number, never a recordset/dict repr.
        self.assertIn("from 10.0 to 25.0", latest.description)
        self.assertNotIn("stock.lot(", latest.description)
