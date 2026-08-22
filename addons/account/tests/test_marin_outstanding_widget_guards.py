from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestOutstandingWidgetGuards(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_data_2 = cls.setup_other_company()

    def _posted_invoice(self, amount=1000.0, company_data=None):
        company_data = company_data or self.company_data
        invoice = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": self.partner_a.id,
                "invoice_date": "2026-06-01",
                "journal_id": company_data["default_journal_sale"].id,
                "invoice_line_ids": [
                    Command.create(
                        {
                            "name": "line",
                            "price_unit": amount,
                            "account_id": company_data["default_account_revenue"].id,
                            "tax_ids": [Command.clear()],
                        }
                    )
                ],
            }
        )
        invoice.action_post()
        return invoice

    def _receivable_line(self, move):
        return move.line_ids.filtered(
            lambda line: line.account_id.account_type == "asset_receivable"
        )

    def _outstanding_credit(self, amount=300.0):
        payment = self.env["account.payment"].create(
            {
                "payment_type": "inbound",
                "partner_type": "customer",
                "partner_id": self.partner_a.id,
                "amount": amount,
                "date": "2026-06-01",
            }
        )
        payment.action_post()
        line = self._receivable_line(payment.move_id)
        self.assertFalse(line.reconciled, "fixture: it must still be outstanding")
        return line


    def test_assign_accepts_a_genuine_outstanding_line(self):
        invoice = self._posted_invoice()
        invoice.js_assign_outstanding_line(self._outstanding_credit(300.0).id)
        self.assertEqual(invoice.payment_state, "partial")

    def test_assign_refuses_an_id_that_is_not_a_line(self):
        invoice = self._posted_invoice()
        with self.assertRaisesRegex(UserError, "cannot be reconciled"):
            invoice.js_assign_outstanding_line(0)

    def test_assign_refuses_a_draft_line(self):
        invoice = self._posted_invoice()
        draft = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": self.partner_a.id,
                "invoice_date": "2026-06-01",
                "invoice_line_ids": [
                    Command.create(
                        {
                            "name": "line",
                            "price_unit": 100.0,
                            "tax_ids": [Command.clear()],
                        }
                    )
                ],
            }
        )
        self.assertEqual(draft.state, "draft")
        with self.assertRaisesRegex(UserError, "cannot be reconciled"):
            invoice.js_assign_outstanding_line(self._receivable_line(draft).id)

    def test_assign_refuses_an_already_reconciled_line(self):
        invoice = self._posted_invoice(amount=300.0)
        credit_line = self._outstanding_credit(300.0)
        invoice.js_assign_outstanding_line(credit_line.id)
        self.assertTrue(credit_line.reconciled, "fixture: it is settled now")
        with self.assertRaisesRegex(UserError, "cannot be reconciled"):
            self._posted_invoice().js_assign_outstanding_line(credit_line.id)

    def test_assign_refuses_a_line_from_another_company(self):
        invoice = self._posted_invoice()
        foreign_line = self._receivable_line(
            self._posted_invoice(company_data=self.company_data_2)
        )
        self.assertNotEqual(foreign_line.company_id, invoice.company_id)
        with self.assertRaisesRegex(UserError, "cannot be reconciled"):
            invoice.js_assign_outstanding_line(foreign_line.id)


    def test_remove_accepts_a_partial_of_this_move(self):
        invoice = self._posted_invoice(amount=500.0)
        invoice.js_assign_outstanding_line(self._outstanding_credit(200.0).id)
        partial = self._receivable_line(invoice).matched_credit_ids
        self.assertTrue(partial)
        invoice.js_remove_outstanding_partial(partial.id)
        self.assertEqual(invoice.payment_state, "not_paid")

    def test_remove_refuses_a_partial_of_another_move(self):
        mine = self._posted_invoice(amount=500.0)
        theirs = self._posted_invoice(amount=500.0)
        theirs.js_assign_outstanding_line(self._outstanding_credit(200.0).id)
        foreign_partial = self._receivable_line(theirs).matched_credit_ids
        self.assertTrue(foreign_partial)
        with self.assertRaisesRegex(UserError, "does not concern this document"):
            mine.js_remove_outstanding_partial(foreign_partial.id)
        self.assertTrue(foreign_partial.exists(), "and it must still be there")

    def test_remove_refuses_an_id_that_is_not_a_partial(self):
        with self.assertRaisesRegex(UserError, "does not concern this document"):
            self._posted_invoice().js_remove_outstanding_partial(0)
