from odoo import Command
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestPaymentAudit(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.bank_journal = cls.company_data["default_journal_bank"]
        cls.other_currency = cls.setup_other_currency("EUR")

    def _payment(self, **vals):
        payment = self.env["account.payment"].create(
            {
                "amount": 100.0,
                "date": "2026-08-01",
                "partner_id": self.partner_a.id,
                "partner_type": "customer",
                "payment_type": "inbound",
                "journal_id": self.bank_journal.id,
                **vals,
            }
        )
        payment.action_post()
        return payment

    def _posted_invoice(self, amount=100.0):
        invoice = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": self.partner_a.id,
                "invoice_date": "2026-08-01",
                "invoice_line_ids": [
                    Command.create(
                        {
                            "name": "line",
                            "price_unit": amount,
                            "account_id": self.company_data["default_account_revenue"].id,
                            "tax_ids": [Command.clear()],
                        }
                    )
                ],
            }
        )
        invoice.action_post()
        return invoice

    def test_posted_payment_can_be_deleted(self):
        payment = self._payment()
        self.assertTrue(payment.move_id, "fixture: the payment must carry a journal entry")
        self.assertTrue(payment.outstanding_account_id, "fixture: and an outstanding account")
        self.assertNotIn(payment.state, ("draft", "canceled"), "fixture: and be posted")
        payment.unlink()
        self.env.flush_all()

    def test_draft_payment_can_be_deleted(self):
        """Control for test_posted_payment_can_be_deleted: the draft path must stay green."""
        payment = self.env["account.payment"].create(
            {"amount": 5.0, "partner_id": self.partner_a.id, "journal_id": self.bank_journal.id}
        )
        payment.unlink()
        self.env.flush_all()

    def test_searching_reconciled_bills_excludes_customer_invoices(self):
        invoice = self._posted_invoice()
        self.env["account.payment.register"].with_context(
            active_model="account.move", active_ids=invoice.ids
        ).create({"journal_id": self.bank_journal.id}).action_create_payments()
        self.env.flush_all()

        Payment = self.env["account.payment"]
        by_invoice = Payment.search([("reconciled_invoice_ids", "in", invoice.ids)])
        by_bill = Payment.search([("reconciled_bill_ids", "in", invoice.ids)])
        self.assertTrue(by_invoice, "fixture: the payment must be findable as an invoice payment")
        self.assertFalse(by_bill, "a customer invoice is not a bill")

    def test_duplicate_banner_follows_the_currency(self):
        stored = self._payment(amount=123.0, date="2026-08-11")
        stored.action_draft()
        self.env.flush_all()
        self.env.invalidate_all()

        draft = self.env["account.payment"].new(
            {
                "amount": 123.0,
                "date": "2026-08-11",
                "partner_id": self.partner_a.id,
                "journal_id": self.bank_journal.id,
            }
        )
        self.assertEqual(
            draft.duplicate_payment_ids._origin,
            stored,
            "fixture: a same-currency payment must register as a duplicate",
        )
        draft.currency_id = self.other_currency
        self.assertFalse(
            draft.duplicate_payment_ids._origin,
            "a payment in another currency is not a duplicate of this one",
        )

    def test_reconciled_invoices_follow_invoice_ids(self):
        payment = self._payment()
        self.assertFalse(payment.reconciled_invoice_ids, "fixture: nothing reconciled yet")
        invoice = self._posted_invoice()
        payment.invoice_ids = [Command.set(invoice.ids)]
        self.env.flush_all()
        self.assertEqual(payment.reconciled_invoice_ids, invoice)

    def test_memo_reaches_the_journal_item_labels(self):
        payment = self._payment(memo="ORIGINAL")
        payment.action_draft()
        self.env.flush_all()
        self.assertEqual(set(payment.move_id.line_ids.mapped("name")), {"Manual Payment: ORIGINAL"})

        payment.write({"memo": "CHANGED"})
        self.env.flush_all()
        self.assertEqual(payment.move_id.ref, "CHANGED", "fixture: the reference does follow")
        self.assertEqual(
            set(payment.move_id.line_ids.mapped("name")),
            {"Manual Payment: CHANGED"},
            "the labels are built from the memo and must follow it",
        )

    def test_sync_survives_several_counterpart_lines(self):
        payment = self._payment()
        payment.action_draft()
        self.env.flush_all()
        _liquidity, counterpart, _writeoff = payment._seek_for_lines()
        line = counterpart[0]
        payment.move_id.with_context(skip_invoice_sync=True).write(
            {
                "line_ids": [
                    Command.update(
                        line.id,
                        {"balance": line.balance / 2, "amount_currency": line.amount_currency / 2},
                    ),
                    Command.create(
                        {
                            "account_id": line.account_id.id,
                            "partner_id": line.partner_id.id,
                            "currency_id": line.currency_id.id,
                            "balance": line.balance / 2,
                            "amount_currency": line.amount_currency / 2,
                            "name": "second counterpart",
                        }
                    ),
                ]
            }
        )
        self.env.flush_all()
        payment.invalidate_recordset()
        self.assertEqual(len(payment._seek_for_lines()[1]), 2, "fixture: two counterpart lines")
        payment.write({"date": "2026-09-09"})
        self.env.flush_all()

    def test_sync_survives_several_liquidity_lines(self):
        """Control for test_sync_survives_several_counterpart_lines: this side is handled."""
        payment = self._payment()
        payment.action_draft()
        self.env.flush_all()
        liquidity, _counterpart, _writeoff = payment._seek_for_lines()
        line = liquidity[0]
        payment.move_id.with_context(skip_invoice_sync=True).write(
            {
                "line_ids": [
                    Command.update(
                        line.id,
                        {"balance": line.balance / 2, "amount_currency": line.amount_currency / 2},
                    ),
                    Command.create(
                        {
                            "account_id": line.account_id.id,
                            "partner_id": line.partner_id.id,
                            "currency_id": line.currency_id.id,
                            "balance": line.balance / 2,
                            "amount_currency": line.amount_currency / 2,
                            "name": "second liquidity",
                        }
                    ),
                ]
            }
        )
        self.env.flush_all()
        payment.invalidate_recordset()
        self.assertEqual(len(payment._seek_for_lines()[0]), 2, "fixture: two liquidity lines")
        payment.write({"date": "2026-09-09"})
        self.env.flush_all()

    def test_onchange_tolerates_a_cleared_payment_type(self):
        self.env["account.payment"].onchange(
            {"payment_type": False, "partner_id": self.partner_a.id, "amount": 5.0},
            ["payment_type"],
            {"payment_type": {}, "partner_id": {}, "journal_id": {}, "amount": {}},
        )
