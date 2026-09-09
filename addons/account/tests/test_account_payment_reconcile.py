from odoo import Command
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestAccountBillPayment(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.bank_journal_1 = cls.company_data["default_journal_bank"]

    def test_bill_state_change_on_payment_state(self):
        bill = self.init_invoice(
            "in_invoice", post=True, partner=self.partner_a, products=self.product_a
        )

        self.bank_journal_1.outbound_payment_channel_ids.payment_account_id = False

        payment = (
            self.env["account.payment.register"]
            .with_context(active_model="account.move", active_ids=bill.ids)
            .create({})
            ._create_payments()
        )
        self.assertEqual(
            bill.payment_state, self.env["account.move"]._get_invoice_in_payment_state()
        )

        payment.action_draft()
        self.assertEqual(payment.state, "draft")
        accountant_module = self.env["ir.module.module"].search(
            [("name", "=", "accountant"), ("state", "=", "installed")]
        )
        expected_state = "not_paid" if accountant_module else "paid"
        self.assertEqual(payment.invoice_ids.payment_state, expected_state)

        payment.unlink()
        self.assertEqual(bill.payment_state, "not_paid")


@tagged("post_install", "-at_install")
class TestPaymentWithoutMoveAllocation(AccountTestInvoicingCommon):
    def test_allocation_never_exceeds_what_a_line_still_owes(self):
        invoice = self.init_invoice(
            "out_invoice", post=True, partner=self.partner_a, amounts=[100.0]
        )
        term_line = invoice.line_ids.filtered(
            lambda line: line.display_type == "payment_term"
        )

        settled = (
            self.env["account.payment.register"]
            .with_context(active_model="account.move", active_ids=invoice.ids)
            .create({"amount": 70.0})
            ._create_payments()
        )
        self.assertTrue(settled)
        self.assertFalse(
            term_line.reconciled, "the premise: partly paid still reads as unreconciled"
        )
        self.assertEqual(term_line.amount_residual_currency, 30.0)

        payment = self.env["account.payment"].create(
            {
                "payment_type": "inbound",
                "partner_type": "customer",
                "partner_id": self.partner_a.id,
                "amount": 50.0,
                "invoice_ids": [Command.set(invoice.ids)],
            }
        )

        vals_list = payment._get_amls_for_payment_without_move()

        against_the_line = sum(
            vals["amount_currency"]
            for vals in vals_list
            if vals.get("reconciled_lines_ids")
        )
        self.assertEqual(
            abs(against_the_line),
            30.0,
            "a line owing 30 must not be allocated more than 30",
        )
        self.assertEqual(
            abs(sum(vals["amount_currency"] for vals in vals_list)),
            50.0,
            "and the whole payment still has to be accounted for",
        )
        self.assertEqual(
            len([vals for vals in vals_list if not vals.get("reconciled_lines_ids")]),
            1,
            "the 20 left over belongs on the partner account as its own line",
        )


@tagged("post_install", "-at_install")
class TestPaymentSupersededDuringReconciliation(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.foreign = cls.setup_other_currency(
            "EUR", rates=[("2017-01-01", 2.0), ("2017-01-08", 4.0)]
        )
        cls.early_payment_term = cls.env["account.payment.term"].create(
            {
                "name": "Early payment",
                "company_id": cls.company_data["company"].id,
                "discount_percentage": 10,
                "discount_days": 10,
                "early_discount": True,
                "line_ids": [
                    Command.create(
                        {"value": "percent", "value_amount": 100, "nb_days": 20}
                    )
                ],
            }
        )

    def _superseded_setup(self):
        partner = self.env["res.partner"].create({"name": "Superseded"})
        invoice = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": partner.id,
                "invoice_date": "2017-01-01",
                "currency_id": self.foreign.id,
                "invoice_payment_term_id": self.early_payment_term.id,
                "invoice_line_ids": [
                    Command.create(
                        {"name": "x", "quantity": 1, "price_unit": 100.0, "tax_ids": []}
                    )
                ],
            }
        )
        invoice.action_post()
        bank = self.company_data["default_journal_bank"]
        payment = self.env["account.payment"].create(
            {
                "payment_type": "inbound",
                "partner_type": "customer",
                "partner_id": partner.id,
                "amount": 90.0,
                "currency_id": self.foreign.id,
                "date": "2017-01-08",
                "journal_id": bank.id,
                "invoice_ids": [Command.set(invoice.ids)],
            }
        )
        self.assertFalse(payment.move_id, "the premise: a payment carrying no entry")
        st_line = self.env["account.bank.statement.line"].create(
            {
                "journal_id": bank.id,
                "date": "2017-01-08",
                "payment_ref": "SUPERSEDED",
                "amount": 22.5,
                "foreign_currency_id": self.foreign.id,
                "amount_currency": 90.0,
                "partner_id": partner.id,
            }
        )
        return invoice, payment, st_line

    def test_a_fully_consumed_payment_is_cancelled_and_says_so(self):
        invoice, payment, st_line = self._superseded_setup()
        messages_before = len(payment.message_ids)

        amls_to_create, _has_exchange_diff = payment._get_amls_for_reconciliation(
            st_line
        )

        self.assertEqual(len(amls_to_create), 1)
        self.assertEqual(
            payment.state,
            "canceled",
            "the whole payment was consumed, so the stand-in is retired",
        )
        self.assertGreater(
            len(payment.message_ids),
            messages_before,
            "and the cancellation is explained on the payment",
        )
        self.assertTrue(
            invoice.matched_payment_ids.filtered("move_id"),
            "a payment carrying a real entry replaced it",
        )

    def test_the_computation_and_the_retirement_are_separable(self):
        self.assertTrue(
            hasattr(self.env["account.payment"], "_supersede_with_payment_move"),
            "the retirement should not be inlined back into the getter",
        )
