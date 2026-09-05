from odoo.tests import tagged

from .common import BaseOrderStockLineCase


@tagged("post_install", "-at_install")
class TestMixinOrderLineStock(BaseOrderStockLineCase):
    def _line(self, **values):
        return self.env["base_order_stock.test.order.line"].new(values)

    def test_draft_line_is_never_a_transfer(self):
        line = self._line(state="draft", product_qty=10.0, qty_transferred=0.0)
        self.assertEqual(line.transfer_state, "no")

    def test_zero_quantity_line_is_no_transfer(self):
        line = self._line(state="done", product_qty=0.0, qty_transferred=0.0)
        self.assertEqual(line.transfer_state, "no")

    def test_nothing_transferred_yet_is_to_do(self):
        line = self._line(state="done", product_qty=10.0, qty_transferred=0.0)
        self.assertEqual(line.qty_to_transfer, 10.0)
        self.assertEqual(line.transfer_state, "to do")

    def test_partial_transfer_is_partial(self):
        line = self._line(state="done", product_qty=10.0, qty_transferred=4.0)
        self.assertEqual(line.qty_to_transfer, 6.0)
        self.assertEqual(line.transfer_state, "partial")

    def test_full_transfer_is_done(self):
        line = self._line(state="done", product_qty=10.0, qty_transferred=10.0)
        self.assertEqual(line.qty_to_transfer, 0.0)
        self.assertEqual(line.transfer_state, "done")

    def test_excess_transfer_is_over_done(self):
        line = self._line(state="done", product_qty=10.0, qty_transferred=12.0)
        self.assertEqual(
            line.qty_to_transfer, 0.0, "excess must clamp, never go negative"
        )
        self.assertEqual(line.transfer_state, "over done")

    def test_section_line_is_never_a_transfer(self):
        line = self._line(
            state="done",
            display_type="line_section",
            product_qty=10.0,
            qty_transferred=0.0,
        )
        self.assertEqual(line.transfer_state, "no")
