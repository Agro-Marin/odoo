from datetime import datetime

from odoo.tests import tagged

from odoo.addons.stock.tests.common import TestStockCommon


@tagged("post_install", "-at_install")
class TestStockTraceabilityReport(TestStockCommon):
    """Cover the pure-stock traceability paths the mrp suite doesn't exercise."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.report = cls.env["stock.traceability.report"]
        cls.tracked = cls.env["product.product"].create(
            {"name": "Traced", "is_storable": True, "tracking": "lot"}
        )
        cls.lot = cls.env["stock.lot"].create(
            {"name": "LOT-TRC", "product_id": cls.tracked.id}
        )

    def _done_move_line(self, src, dst, date):
        move = self.env["stock.move"].create(
            {
                "product_id": self.tracked.id,
                "product_uom_qty": 5,
                "location_id": src.id,
                "location_dest_id": dst.id,
            }
        )
        line = self.env["stock.move.line"].create(
            {
                "move_id": move.id,
                "product_id": self.tracked.id,
                "lot_id": self.lot.id,
                "location_id": src.id,
                "location_dest_id": dst.id,
                "quantity": 5,
            }
        )
        move.state = "done"
        line.date = date
        return line

    def _build_chain(self):
        """supplier -> stock -> shelf_1 -> customer, one lot the whole way."""
        ml1 = self._done_move_line(
            self.supplier_location, self.stock_location, datetime(2026, 1, 1)
        )
        ml2 = self._done_move_line(
            self.stock_location, self.shelf_1, datetime(2026, 2, 1)
        )
        ml3 = self._done_move_line(
            self.shelf_1, self.customer_location, datetime(2026, 3, 1)
        )
        return ml1, ml2, ml3

    def test_get_move_lines_depth_is_deterministic(self):
        ml1, ml2, ml3 = self._build_chain()
        # line_id=None walks the chain to the end (used for the unfoldable test)
        self.assertEqual(self.report._get_move_lines(ml3).ids, (ml2 | ml1).ids)
        # a truthy line_id returns exactly one upstream generation, and its depth
        # must not depend on the *value* of that id...
        self.assertEqual(self.report._get_move_lines(ml3, line_id=999999).ids, ml2.ids)
        # ...including when the client row counter happens to equal a real
        # move-line id. Regression: the old ``line_id in lines.ids`` clause let
        # such a collision silently expand this to two levels.
        self.assertEqual(self.report._get_move_lines(ml3, line_id=ml2.id).ids, ml2.ids)

    def test_has_upstream_move_lines(self):
        ml1, _ml2, ml3 = self._build_chain()
        self.assertTrue(self.report._has_upstream_move_lines(ml3))
        self.assertFalse(self.report._has_upstream_move_lines(ml1))

    def test_row_ids_are_deterministic(self):
        self._build_chain()
        ctx = {"active_id": self.lot.id, "model": "stock.lot"}
        first = self.report.with_context(**ctx).get_lines()
        second = self.report.with_context(**ctx).get_lines()
        self.assertTrue(first, "the lot has done move lines to report")
        ids = [line["id"] for line in first]
        # stable across identical calls (no process-global counter)...
        self.assertEqual(ids, [line["id"] for line in second])
        # ...and a plain 1..N per response
        self.assertEqual(ids, list(range(1, len(first) + 1)))

    def test_get_lines_tolerates_partial_kwargs(self):
        # Regression: get_lines used ``kw and kw["model_name"]`` which raised
        # KeyError when kw was non-empty but missing a key.
        result = self.report.with_context(model="stock.lot").get_lines(level=2)
        self.assertEqual(result, [])
