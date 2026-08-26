from odoo.tests import tagged

from .common import BaseOrderTestCase


@tagged("post_install", "-at_install")
class TestInvoiceState(BaseOrderTestCase):
    """The invoicing state machine, line level and order level.

    `mixin.order.line.invoice._compute_invoice_state` and
    `mixin.order.invoice._resolve_invoice_state` decide what a document
    reports as its billing status. Both were shadowed on every concrete model
    that ships, so the branches below -- over-invoiced, partially invoiced,
    the ordered/delivered policy split -- were reachable in production and
    asserted nowhere.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product.base_order_test_invoice_policy = "ordered"

    def _line(self, invoiced=0.0, qty=10.0, **kw):
        return self._make_line(
            product_qty=qty,
            price_unit=100.0,
            qty_invoiced_input=invoiced,
            **kw,
        )

    # ─── line level ───────────────────────────────────────────────

    def test_nothing_invoiced_is_to_do(self):
        self.assertEqual(self._line(invoiced=0.0).invoice_state, "to do")

    def test_partly_invoiced_is_partial(self):
        self.assertEqual(self._line(invoiced=4.0).invoice_state, "partial")

    def test_fully_invoiced_is_done(self):
        self.assertEqual(self._line(invoiced=10.0).invoice_state, "done")

    def test_invoiced_beyond_the_ordered_quantity_is_over_done(self):
        self.assertEqual(self._line(invoiced=12.0).invoice_state, "over done")

    def test_a_line_of_zero_quantity_has_nothing_to_invoice(self):
        self.assertEqual(self._line(qty=0.0).invoice_state, "no")

    def test_a_display_line_has_nothing_to_invoice(self):
        order = self._make_order()
        section = self.env["base.order.test.line"].create(
            {
                "order_id": order.id,
                "display_type": "line_section",
                "name": "A section",
            }
        )

        self.assertEqual(section.invoice_state, "no")

    def test_a_delivered_policy_line_waits_for_the_delivery(self):
        self.product.base_order_test_invoice_policy = "transferred"
        line = self._line(invoiced=0.0, qty=10.0)

        self.assertEqual(line.invoice_state, "to do")

    # ─── order level ──────────────────────────────────────────────

    def test_a_draft_order_reports_nothing_to_invoice(self):
        order = self._make_order()
        self._line(order=order, invoiced=0.0)

        self.assertEqual(order.invoice_state, "no")

    def test_a_confirmed_order_with_nothing_invoiced_is_to_do(self):
        order = self._make_order()
        self._line(order=order, invoiced=0.0)
        order.action_confirm()

        self.assertEqual(order.invoice_state, "to do")

    def test_a_confirmed_order_fully_invoiced_is_done(self):
        order = self._make_order()
        self._line(order=order, invoiced=10.0)
        order.action_confirm()

        self.assertEqual(order.invoice_state, "done")

    def test_one_invoiced_line_and_one_not_is_partial(self):
        order = self._make_order()
        self._line(order=order, invoiced=10.0)
        self._line(order=order, invoiced=0.0)
        order.action_confirm()

        self.assertEqual(order.invoice_state, "partial")

    def test_an_over_invoiced_line_carries_the_order_to_over_done(self):
        order = self._make_order()
        self._line(order=order, invoiced=12.0)
        self._line(order=order, invoiced=10.0)
        order.action_confirm()

        self.assertEqual(order.invoice_state, "over done")

    def test_forcing_the_state_reports_done_whatever_the_lines_say(self):
        order = self._make_order()
        self._line(order=order, invoiced=0.0)
        order.action_confirm()
        self.assertEqual(order.invoice_state, "to do")

        order.action_force_invoice_state()

        self.assertEqual(order.invoice_state, "done")

    def test_unforcing_the_state_hands_it_back_to_the_lines(self):
        order = self._make_order()
        self._line(order=order, invoiced=0.0)
        order.action_confirm()
        order.action_force_invoice_state()

        order.action_unforce_invoice_state()

        self.assertEqual(order.invoice_state, "to do")

    def test_a_cancelled_order_reports_nothing_to_invoice(self):
        order = self._make_order()
        self._line(order=order, invoiced=0.0)
        order.action_confirm()
        order.action_cancel()

        self.assertEqual(order.invoice_state, "no")
