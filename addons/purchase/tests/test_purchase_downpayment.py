from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.purchase.tests.test_purchase_invoice import TestPurchaseToInvoiceCommon


@tagged("-at_install", "post_install")
class TestPurchaseDownpayment(TestPurchaseToInvoiceCommon):
    def test_downpayment_basic(self):
        po = self.init_purchase(confirm=False, products=[self.product_order])
        po.line_ids.product_qty = 10.0
        po.action_confirm()

        dp_bill = self.init_invoice("in_invoice", amounts=[69.00], post=True)

        match_lines = self.env["purchase.bill.line.match"].search(
            [("partner_id", "=", self.partner_a.id)]
        )
        action = match_lines.action_add_to_po()

        wizard = (
            self.env["bill.to.po.wizard"]
            .with_context({**action["context"], "active_ids": match_lines.ids})
            .create({})
        )
        wizard.action_add_downpayment()

        po_dp_section_line = po.line_ids.filtered(
            lambda l: l.display_type == "line_section" and l.is_downpayment
        )
        self.assertEqual(len(po_dp_section_line), 1)
        po_dp_line = po.line_ids.filtered(
            lambda l: l.display_type != "line_section" and l.is_downpayment
        )
        self.assertEqual(
            po_dp_line.name,
            "Down Payment (ref: %s)" % dp_bill.invoice_line_ids.display_name,
        )
        self.assertEqual(po_dp_line.sequence, po_dp_section_line.sequence + 1)

        generated_bill = po.create_invoice()

        self.assertRecordValues(
            generated_bill.invoice_line_ids,
            [
                {
                    "product_id": self.product_order.id,
                    "display_type": "product",
                    "quantity": 10,
                    "is_downpayment": False,
                    "balance": 10.0 * self.product_order.standard_price,
                },
                {
                    "product_id": False,
                    "display_type": "line_section",
                    "quantity": 0,
                    "is_downpayment": False,
                    "balance": 0.0,
                },
                {
                    "product_id": False,
                    "display_type": "product",
                    "quantity": -1,
                    "is_downpayment": True,
                    "balance": -69.0,
                },
            ],
        )

        final_bill = generated_bill.copy()
        generated_bill.action_cancel()
        generated_bill.unlink()
        final_bill.invoice_date = fields.Date.from_string("2019-01-02")
        self.assertFalse(final_bill.line_ids.purchase_line_ids)

        self.env.flush_all()
        match_lines = self.env["purchase.bill.line.match"].search(
            [("partner_id", "=", self.partner_a.id)]
        )
        match_lines.action_match_lines()

        final_bill.action_post()

        self.assertEqual(po.invoice_state, "done")
        self.assertRecordValues(
            po_dp_line,
            [
                {
                    "qty_invoiced": 0,
                    "invoice_line_ids": dp_bill.invoice_line_ids.ids
                    + final_bill.invoice_line_ids[-1:].ids,
                }
            ],
        )
        self.env.flush_all()
        self.assertFalse(
            self.env["purchase.bill.line.match"].search(
                [("partner_id", "=", self.partner_a.id)]
            )
        )

    def test_product_supplierinfo_downpayment(self):
        self.product_a.seller_ids = [
            Command.create(
                {"partner_id": self.partner_a.id, "price": 750.0, "min_qty": 10}
            )
        ]

        down_po = self.env["purchase.order"].create(
            {
                "partner_id": self.partner_a.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product_a.id,
                            "product_qty": 10,
                        }
                    )
                ],
            }
        )

        product_line = down_po.line_ids
        self.assertEqual(product_line.price_unit, 750.0)
        down_po.line_ids.price_unit = 800
        down_po.action_confirm()

        self.init_invoice("in_invoice", amounts=[1600.00], post=True)

        match_lines = self.env["purchase.bill.line.match"].search(
            [("partner_id", "=", self.partner_a.id)]
        )
        action = match_lines.action_add_to_po()

        wizard = (
            self.env["bill.to.po.wizard"]
            .with_context({**action["context"], "active_ids": match_lines.ids})
            .create({})
        )
        wizard.action_add_downpayment()

        self.assertEqual(product_line.price_unit, 800.0)

    def test_downpayment_in_accrued_expense_entry(self):
        po = self.init_purchase(confirm=True, products=[self.product_order])

        self.init_invoice("in_invoice", amounts=[1600.00], post=True)

        match_lines = self.env["purchase.bill.line.match"].search(
            [("partner_id", "=", self.partner_a.id)]
        )
        action = match_lines.action_add_to_po()

        wizard = (
            self.env["bill.to.po.wizard"]
            .with_context({**action["context"], "active_ids": match_lines.ids})
            .create({})
        )
        wizard.action_add_downpayment()

        account_expense = self.company_data["default_account_expense"]
        accrued_wizard = (
            self.env["account.accrued.orders.wizard"]
            .with_context(
                active_model="purchase.order",
                active_ids=po.ids,
            )
            .create(
                {
                    "account_id": self.company_data["default_account_expense"].id,
                    "date": fields.Date.today(),
                }
            )
        )

        po.line_ids.qty_transferred = 1

        self.assertRecordValues(
            self.env["account.move"]
            .search(accrued_wizard.create_entries()["domain"])
            .line_ids,
            [
                {"account_id": account_expense.id, "debit": 0, "credit": 235.0},
                {
                    "account_id": accrued_wizard.account_id.id,
                    "debit": 235.0,
                    "credit": 0,
                },
                {"account_id": account_expense.id, "debit": 235.0, "credit": 0},
                {
                    "account_id": accrued_wizard.account_id.id,
                    "debit": 0,
                    "credit": 235.0,
                },
            ],
        )
        self.assertFalse(
            self.env["account.move"]
            .search(accrued_wizard.create_entries()["domain"])
            .line_ids.filtered(lambda l: l.is_downpayment)
        )

    def test_downpayment_exchange_rate(self):
        self.env["res.currency.rate"].create(
            {"currency_id": self.other_currency.id, "rate": 1.5}
        )

        po = self.init_purchase(products=[self.product_order])
        po.action_confirm()
        self.init_invoice(
            "in_invoice", amounts=[100.00], post=True, currency=self.other_currency
        )

        match_lines = self.env["purchase.bill.line.match"].search(
            [("partner_id", "=", self.partner_a.id)]
        )
        action = match_lines.action_add_to_po()

        wizard = (
            self.env["bill.to.po.wizard"]
            .with_context({**action["context"], "active_ids": match_lines.ids})
            .create({})
        )
        wizard.action_add_downpayment()

        po_dp_line = po.line_ids.filtered(
            lambda l: l.display_type != "line_section" and l.is_downpayment
        )
        self.assertEqual(po_dp_line.price_unit, 66.67)


@tagged("-at_install", "post_install")
class TestPurchaseDownpaymentWizard(TestPurchaseToInvoiceCommon):
    def _order(self):
        po = self.init_purchase(
            confirm=False, products=[self.product_order], taxes=self.env["account.tax"]
        )
        po.line_ids.product_qty = 10.0
        po.action_confirm()
        return po

    def _wizard(self, po, **vals):
        return (
            self.env["purchase.advance.payment.inv"]
            .with_context(active_model="purchase.order", active_ids=po.ids)
            .create(vals)
        )

    def test_percentage_down_payment_bill_is_deducted_by_the_final_bill(self):
        po = self._order()
        total = po.amount_untaxed

        self._wizard(
            po, advance_payment_method="percentage", amount=20
        ).create_invoices()
        dp_bill = po.invoice_ids
        self.assertEqual(dp_bill.move_type, "in_invoice")
        self.assertAlmostEqual(dp_bill.amount_untaxed, total * 0.2)
        dp_line = po.line_ids.filtered(
            lambda line: line.is_downpayment and not line.display_type
        )
        self.assertEqual(len(dp_line), 1)
        self.assertEqual(dp_bill.invoice_line_ids.purchase_line_ids, dp_line)
        dp_bill.invoice_date = fields.Date.today()
        dp_bill.action_post()

        final_bill = po.create_invoice()
        deduction = final_bill.invoice_line_ids.filtered(
            lambda line: line.is_downpayment and line.display_type == "product"
        )
        self.assertEqual(deduction.quantity, -1)
        self.assertAlmostEqual(final_bill.amount_untaxed, total * 0.8)

    def test_fixed_down_payment_bill(self):
        po = self._order()
        self._wizard(
            po, advance_payment_method="fixed", fixed_amount=100
        ).create_invoices()
        self.assertAlmostEqual(po.invoice_ids.amount_total, 100)

    def test_down_payment_amount_must_be_positive_and_at_most_the_whole(self):
        po = self._order()
        with self.assertRaisesRegex(UserError, "must be positive"):
            self._wizard(
                po, advance_payment_method="percentage", amount=0
            ).create_invoices()
        with self.assertRaisesRegex(UserError, "cannot exceed 100%"):
            self._wizard(
                po, advance_payment_method="percentage", amount=120
            ).create_invoices()

    def _down_payment(self, po, percentage=20):
        self._wizard(
            po, advance_payment_method="percentage", amount=percentage
        ).create_invoices()
        dp_line = po.line_ids.filtered(
            lambda line: line.is_downpayment and not line.display_type
        )
        return po.invoice_ids, dp_line

    def test_deleting_a_draft_down_payment_bill_removes_its_order_line(self):
        po = self._order()
        dp_bill, dp_line = self._down_payment(po)

        dp_bill.unlink()

        self.assertFalse(dp_line.exists())
        self.assertFalse(
            po.line_ids.filtered(
                lambda line: not line.display_type and line.is_downpayment
            )
        )

    def test_the_final_bill_deducts_the_amount_the_down_payment_bill_was_posted_at(
        self,
    ):
        po = self._order()
        dp_bill, dp_line = self._down_payment(po)
        dp_bill.invoice_line_ids.price_unit = 150.0
        dp_bill.invoice_date = fields.Date.today()
        dp_bill.action_post()

        self.assertEqual(dp_line.price_unit, 150.0)
        final_bill = po.create_invoice()
        self.assertAlmostEqual(final_bill.amount_untaxed, po.amount_untaxed - 150.0)

    def test_the_down_payment_line_is_named_after_its_bill(self):
        po = self._order()
        dp_bill, dp_line = self._down_payment(po)
        self.assertIn("(Draft)", dp_line.name)

        dp_bill.ref = "VND/0042"
        dp_bill.invoice_date = fields.Date.from_string("2019-01-02")
        dp_bill.action_post()
        self.assertEqual(dp_line.name, "Down Payment (ref: VND/0042 on 01/02/2019)")

        dp_bill.action_draft()
        dp_bill.action_cancel()
        self.assertEqual(dp_line.name, "Down Payment (Cancelled)")


@tagged("-at_install", "post_install")
class TestPurchaseCancelGuard(TestPurchaseToInvoiceCommon):
    def test_a_fully_refunded_bill_no_longer_blocks_cancelling_the_order(self):
        po = self.init_purchase(confirm=True, products=[self.product_order])
        bill = po.create_invoice()
        bill.invoice_date = fields.Date.today()
        bill.action_post()

        with self.assertRaisesRegex(UserError, bill.name):
            po.action_cancel()
        bill._reverse_moves([{"invoice_date": fields.Date.today()}], cancel=True)
        self.assertEqual(bill.payment_state, "reversed")

        po.action_cancel()
        self.assertEqual(po.state, "cancel")
