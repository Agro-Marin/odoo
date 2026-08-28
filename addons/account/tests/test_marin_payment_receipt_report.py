from odoo import Command
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestPaymentReceiptReport(AccountTestInvoicingCommon):
    def _paid_invoice(self, amount=1000.0, paid=400.0):
        invoice = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": self.partner_a.id,
                "invoice_date": "2026-06-01",
                "invoice_line_ids": [
                    Command.create(
                        {
                            "name": "line",
                            "price_unit": amount,
                            "tax_ids": [Command.clear()],
                        }
                    )
                ],
            }
        )
        invoice.action_post()
        wizard = (
            self.env["account.payment.register"]
            .with_context(active_model="account.move", active_ids=invoice.ids)
            .create({"amount": paid})
        )
        payment = wizard._create_payments()
        return invoice, payment

    def _render(self, payment):
        return (
            self.env["ir.actions.report"]
            ._render_qweb_html("account.report_payment_receipt", payment.ids)[0]
            .decode()
        )

    def test_receipt_lists_the_invoice_and_the_amount_settled(self):
        invoice, payment = self._paid_invoice(amount=1000.0, paid=400.0)
        html = self._render(payment)
        self.assertIn(invoice.name, html, "the settled invoice must be listed")
        self.assertIn(payment.move_id.name, html, "so must the payment line under it")
        self.assertIn("1,000.00", html, "the invoice total")
        self.assertIn("400.00", html, "the amount this payment settled")

    def test_receipt_renders_for_a_payment_settling_two_invoices(self):
        first, _p = self._paid_invoice(amount=500.0, paid=100.0)
        second = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": self.partner_a.id,
                "invoice_date": "2026-06-02",
                "invoice_line_ids": [
                    Command.create(
                        {
                            "name": "line",
                            "price_unit": 700.0,
                            "tax_ids": [Command.clear()],
                        }
                    )
                ],
            }
        )
        second.action_post()
        wizard = (
            self.env["account.payment.register"]
            .with_context(active_model="account.move", active_ids=(first + second).ids)
            .create({"group_payment": True})
        )
        payment = wizard._create_payments()
        html = self._render(payment)
        for invoice in (first, second):
            self.assertIn(invoice.name, html)

    def test_receipt_renders_when_the_payment_settles_nothing(self):
        payment = self.env["account.payment"].create(
            {
                "payment_type": "inbound",
                "partner_type": "customer",
                "partner_id": self.partner_a.id,
                "amount": 50.0,
                "date": "2026-06-01",
            }
        )
        payment.action_post()
        html = self._render(payment)
        self.assertIn(self.partner_a.name, html)

    def test_receipt_title_names_the_kind_of_document(self):
        """The receipt heading must name the document, not always "Payment Receipt"."""
        cases = {
            ("inbound", "customer"): "Payment Receipt",
            ("outbound", "supplier"): "Remittance Advice",
            ("outbound", "customer"): "Refund Confirmation",
            ("inbound", "supplier"): "Refund Confirmation",
        }
        for (payment_type, partner_type), expected in cases.items():
            with self.subTest(payment_type=payment_type, partner_type=partner_type):
                payment = self.env["account.payment"].create(
                    {
                        "payment_type": payment_type,
                        "partner_type": partner_type,
                        "partner_id": self.partner_a.id,
                        "amount": 100.0,
                    }
                )
                self.assertEqual(payment.payment_receipt_title, expected)
