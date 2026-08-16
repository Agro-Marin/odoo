from operator import ge, gt, le, lt

from odoo import fields
from odoo.tests import tagged

from odoo.addons.stock.tests.common import TestStockCommon


@tagged("post_install", "-at_install")
class TestQuantDormancy(TestStockCommon):
    """``date_last_movement`` / ``days_since_last_movement`` on ``stock.quant``.

    Dormancy is "nothing has moved", which is not "nothing has happened": an
    inventory count writes move lines too, and counting those as movement would
    report a diligently counted warehouse as holding no dormant stock at all.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dormant_product, cls.other_product = cls.env["product.product"].create(
            [
                {"name": "Dormant Widget", "is_storable": True},
                {"name": "Other Widget", "is_storable": True},
            ]
        )

    def _stock_quant(self, product):
        return self.env["stock.quant"].search(
            [
                ("product_id", "=", product.id),
                ("location_id", "=", self.stock_location.id),
            ]
        )

    def _dormant_quant(self, product, days, quantity=10.0):
        """Stock `quantity` of `product` and backdate its arrival by `days`."""
        self.env["stock.quant"]._update_available_quantity(
            product, self.stock_location, quantity
        )
        quant = self._stock_quant(product)
        quant.write(
            {"in_date": fields.Datetime.subtract(fields.Datetime.now(), days=days)}
        )
        return quant

    def test_never_moved_ages_from_in_date(self):
        quant = self._dormant_quant(self.dormant_product, 100)
        self.assertFalse(
            quant.date_last_movement, "no move line has ever touched this quant"
        )
        self.assertEqual(quant.days_since_last_movement, 100)

    def test_inventory_count_is_not_a_movement(self):
        """Counting 100-day-old stock today leaves it 100 days dormant."""
        quant = self._dormant_quant(self.dormant_product, 100)
        counted = quant.with_context(inventory_mode=True)
        counted.inventory_quantity = 12.0
        counted.action_apply_inventory()

        quant.invalidate_recordset()
        self.assertTrue(quant.last_count_date, "the count is recorded, as a count")
        self.assertFalse(quant.date_last_movement)
        self.assertEqual(quant.days_since_last_movement, 100)

    def test_real_movement_sets_the_clock(self):
        quant = self._dormant_quant(self.dormant_product, 100)
        move = self.env["stock.move"].create(
            {
                "product_id": self.dormant_product.id,
                "product_uom_id": self.uom_unit.id,
                "product_uom_qty": 4.0,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
            }
        )
        move._action_confirm()
        move._action_assign()
        move.picked = True
        move._action_done()
        move.move_line_ids.date = fields.Datetime.subtract(
            fields.Datetime.now(), days=10
        )

        # The compute cannot depend on move lines (see its docstring), so the
        # read below must not be served from a pre-move cache entry.
        quant.invalidate_recordset()
        self.assertEqual(quant.quantity, 6.0)
        self.assertTrue(quant.date_last_movement)
        self.assertEqual(
            quant.days_since_last_movement,
            10,
            "the picking, not the 100-day-old arrival, is what stopped last",
        )

    def test_search_agrees_with_the_compute(self):
        quants = self._dormant_quant(self.dormant_product, 5) | self._dormant_quant(
            self.other_product, 200
        )
        comparators = {">=": ge, ">": gt, "<=": le, "<": lt}
        for days in (1, 5, 100, 200, 500):
            for symbol, compare in comparators.items():
                with self.subTest(days=days, operator=symbol):
                    expected = quants.filtered(
                        lambda quant, c=compare, n=days: c(
                            quant.days_since_last_movement, n
                        )
                    )
                    found = self.env["stock.quant"].search(
                        [
                            ("id", "in", quants.ids),
                            ("days_since_last_movement", symbol, days),
                        ]
                    )
                    self.assertEqual(found, expected)

    def test_search_ignores_inventory_counts(self):
        """The SQL must exclude counts exactly as the compute does."""
        quant = self._dormant_quant(self.dormant_product, 100)
        counted = quant.with_context(inventory_mode=True)
        counted.inventory_quantity = 12.0
        counted.action_apply_inventory()

        found = self.env["stock.quant"].search(
            [("id", "=", quant.id), ("days_since_last_movement", ">=", 90)]
        )
        self.assertEqual(found, quant)

    def test_search_unsupported_operator(self):
        """Equality has no useful day-window meaning; it must not silently match."""
        self._dormant_quant(self.dormant_product, 100)
        with self.assertRaises(NotImplementedError):
            self.env["stock.quant"].search([("days_since_last_movement", "=", 100)])
