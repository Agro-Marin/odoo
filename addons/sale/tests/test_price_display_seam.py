from unittest.mock import patch

from odoo.tests import tagged

from odoo.addons.sale.models.sale_order_line import SaleOrderLine
from odoo.addons.sale.tests.common import SaleCommon


@tagged("post_install", "-at_install")
class TestPriceDisplaySeam(SaleCommon):
    """`_get_price_display` is what a line type overrides to price itself.

    event_sale prices off the ticket, event_booth_sale off the booth and
    sale_loyalty off the reward, all through this one method. It is easy to lose
    without noticing, because `_compute_price_and_discount` can compute the same
    number inline for a regular line and still look right for every product that
    is priced off its own product -- which is all of them in this module's own
    tests. This asserts the seam is consulted, not the answer it happens to give.
    """

    def test_the_price_compute_goes_through_the_display_seam(self):
        origin = SaleOrderLine._get_price_display
        seen = []

        def _spy(line, *args, **kwargs):
            seen.append(line.id)
            return origin(line, *args, **kwargs)

        line = self.env["sale.order.line"].create({
            "order_id": self.empty_order.id,
            "product_id": self.product.id,
        })
        self.env.flush_all()
        seen.clear()
        with patch.object(SaleOrderLine, "_get_price_display", _spy):
            line.invalidate_recordset(["price_unit", "discount"])
            line._compute_price_and_discount()

        self.assertIn(
            line.id, seen,
            "a regular line must price itself through _get_price_display; "
            "inlining the computation makes every override of it dead",
        )

    def test_an_override_of_the_seam_reaches_price_unit(self):
        """What the seam returns is what the line is priced at."""
        line = self.env["sale.order.line"].create({
            "order_id": self.empty_order.id,
            "product_id": self.product.id,
        })
        self.env.flush_all()

        def _fixed(line, *args, **kwargs):
            return 123.45

        with patch.object(SaleOrderLine, "_get_price_display", _fixed):
            line.invalidate_recordset(["price_unit", "discount"])
            line.with_context(force_price_recomputation=True)._compute_price_and_discount()

        self.assertEqual(line.price_unit, 123.45)
