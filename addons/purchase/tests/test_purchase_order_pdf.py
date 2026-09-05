from odoo import Command
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("-at_install", "post_install")
class TestPurchaseOrderPdfPaymentTerms(AccountTestInvoicingCommon):
    """The PO the vendor receives must not announce terms the order has none of.

    `payment_term_id` is optional (`base_order.mixin.order`, a compute with
    `readonly=False` that defaults from the vendor), so a vendor with no
    `property_supplier_payment_term_id` produces an order with none -- and the
    template printed the bold label anyway, followed by nothing.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.vendor_without_terms = cls.env["res.partner"].create(
            {"name": "Vendor without payment terms"},
        )

    def _order_for(self, partner):
        return self.env["purchase.order"].create(
            {
                "partner_id": partner.id,
                "line_ids": [
                    Command.create(
                        {
                            "name": "A line",
                            "product_id": self.product_a.id,
                            "product_qty": 1,
                            "price_unit": 100.0,
                            "tax_ids": [Command.clear()],
                        },
                    ),
                ],
            },
        )

    def _render(self, order):
        return (
            self.env["ir.actions.report"]
            ._render_qweb_html("purchase.report_purchaseorder", order.ids)[0]
            .decode()
        )

    def test_label_is_absent_when_the_order_has_no_payment_terms(self):
        order = self._order_for(self.vendor_without_terms)

        self.assertFalse(
            order.payment_term_id,
            "fixture guard: this vendor must produce an order with no terms",
        )
        self.assertNotIn("Payment Terms", self._render(order))

    def test_label_and_value_are_printed_when_the_order_has_payment_terms(self):
        order = self._order_for(self.partner_a)

        self.assertTrue(
            order.payment_term_id,
            "fixture guard: partner_a carries a supplier payment term",
        )
        html = self._render(order)
        self.assertIn("Payment Terms", html)
        self.assertIn(order.payment_term_id.name, html)
