from lxml import etree

from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.tests import tagged

from odoo.addons.sale.tests.common import SaleCommon

CLOSE_ACTION = "sale.action_sale_order_force_invoice_state"


@tagged("post_install", "-at_install")
class TestSaleOrderForceInvoiced(SaleCommon):
    """Reaching `force_fully_invoiced` from the interface.

    27 confirmed orders sit in `invoice_state` `to do` or `partial`, 22 of them
    from 2022-2024, and they are what the "To Invoice" filter shows. The mixin
    has carried the flag that closes them since `c0180669ca00`; until now its
    only caller was a test.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product.invoice_policy = "ordered"
        cls.order = cls.env["sale.order"].create(
            {
                "partner_id": cls.partner.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": cls.product.id,
                            "product_qty": 4.0,
                        },
                    ),
                ],
            },
        )
        cls.order.action_confirm()

    def _run_close_action(self, orders):
        """Close through the binding a user would actually click."""
        return (
            self.env.ref(CLOSE_ACTION)
            .with_context(active_model=orders._name, active_ids=orders.ids)
            .run()
        )

    def _bodies(self, order):
        return order.message_ids.mapped("body")

    def test_the_order_starts_out_waiting_to_be_invoiced(self):
        self.assertEqual(self.order.invoice_state, "to do")

    def test_the_close_action_reports_the_order_fully_invoiced(self):
        self._run_close_action(self.order)
        self.assertTrue(self.order.force_fully_invoiced)
        self.assertEqual(self.order.invoice_state, "done")

    def test_closing_a_quotation_is_refused(self):
        """Nothing is pending on a draft order, so closing one would only hide
        it from the invoicing list."""
        with self.assertRaises(UserError):
            self.empty_order.action_force_invoice_state()
        self.assertFalse(self.empty_order.force_fully_invoiced)

    def test_closing_says_so_in_the_chatter(self):
        self._run_close_action(self.order)
        self.assertTrue(
            [b for b in self._bodies(self.order) if "Invoicing closed" in b],
            "closing an order by hand has to leave a trace: %s"
            % self._bodies(self.order),
        )

    def test_closing_an_already_closed_order_says_nothing_twice(self):
        self._run_close_action(self.order)
        before = len(self.order.message_ids)
        self._run_close_action(self.order)
        self.assertEqual(len(self.order.message_ids), before)

    def test_reopening_brings_back_the_pending_state_and_says_so(self):
        self._run_close_action(self.order)
        self.order.action_unforce_invoice_state()
        self.assertFalse(self.order.force_fully_invoiced)
        self.assertEqual(self.order.invoice_state, "to do")
        self.assertTrue(
            [b for b in self._bodies(self.order) if "Invoicing reopened" in b],
        )

    def test_reopening_an_open_order_says_nothing(self):
        before = len(self.order.message_ids)
        self.order.action_unforce_invoice_state()
        self.assertEqual(len(self.order.message_ids), before)

    def test_the_reopen_button_is_reachable_on_the_order_form(self):
        arch = etree.fromstring(
            self.env["sale.order"].get_view(
                self.env.ref("sale.view_sale_order_form").id,
                "form",
            )["arch"],
        )
        self.assertTrue(
            arch.xpath("//header/button[@name='action_unforce_invoice_state']"),
            "no way to reopen an order whose invoicing was closed by mistake",
        )
        self.assertTrue(
            arch.xpath("//header/field[@name='force_fully_invoiced']"),
            "the button's modifier cannot read a field the form never loads",
        )
