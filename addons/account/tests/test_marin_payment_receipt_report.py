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

    def _epd_invoice(self, amount=1000.0, percentage=10, days=10):
        term = self.env["account.payment.term"].create(
            {
                "name": "10% within 10 days",
                "early_discount": True,
                "discount_percentage": percentage,
                "discount_days": days,
                "early_pay_discount_computation": "excluded",
                "line_ids": [
                    Command.create(
                        {"value": "percent", "nb_days": 0, "value_amount": 100}
                    )
                ],
            }
        )
        invoice = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": self.partner_a.id,
                "invoice_date": "2026-06-01",
                "invoice_payment_term_id": term.id,
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
        return invoice

    def test_receipt_shows_the_early_payment_discount_on_its_own_line(self):
        """A discounted payment must not read as if it settled the full invoice."""
        invoice = self._epd_invoice(amount=1000.0, percentage=10)
        payment_term_line = invoice.line_ids.filtered(
            lambda line: line.display_type == "payment_term"
        )
        discounted = payment_term_line.discount_amount_currency

        wizard = (
            self.env["account.payment.register"]
            .with_context(active_model="account.move", active_ids=invoice.ids)
            .create({"payment_date": "2026-06-05"})
        )
        payment = wizard._create_payments()

        rows = invoice._get_reconciled_invoices_partials_for_receipt()
        self.assertEqual(
            len(rows), 2, "the payment and its discount must be two separate rows"
        )
        payment_row, discount_row = rows
        self.assertEqual(
            payment_row["amount_invoice"],
            -discounted,
            "the payment row must show what was actually settled, not the gross",
        )
        self.assertEqual(discount_row["name"], "Early Payment Discount")
        self.assertEqual(discount_row["amount_invoice"], -100.0)
        self.assertEqual(
            invoice.amount_total
            + payment_row["amount_invoice"]
            + discount_row["amount_invoice"],
            invoice.amount_residual,
            "the rows must reduce the invoice total to the residual printed"
            " underneath them, otherwise the receipt contradicts itself",
        )

        html = self._render(payment)
        self.assertIn("Early Payment Discount", html)
