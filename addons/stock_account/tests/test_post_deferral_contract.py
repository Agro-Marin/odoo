from datetime import timedelta

from freezegun import freeze_time

from odoo import Command, fields
from odoo.tests import tagged

from odoo.addons.stock_account.tests.common import TestStockValuationCommon


@tagged("post_install", "-at_install")
class TestPostDeferralContract(TestStockValuationCommon):
    def _out_invoice(self, date):
        return self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": self.vendor.id,
                "invoice_date": date,
                "date": date,
                "invoice_line_ids": [
                    Command.create(
                        {
                            "product_id": self.product_standard_auto.id,
                            "quantity": 1,
                            "price_unit": 10.0,
                            "tax_ids": [],
                        }
                    )
                ],
            }
        )

    def _cogs(self, invoice):
        return invoice.line_ids.filtered(lambda line: line.display_type == "cogs")

    def test_soft_post_defers_without_creating_cogs(self):
        today = fields.Date.context_today(self.env.user)
        invoice = self._out_invoice(today + timedelta(days=30))

        posted = invoice._post(soft=True)

        self.assertFalse(
            posted, "a future-dated move must not be posted by a soft post"
        )
        self.assertEqual(invoice.state, "draft")
        self.assertEqual(invoice.auto_post, "at_date")
        self.assertFalse(
            self._cogs(invoice),
            "COGS lines were created on a move the soft post deferred",
        )

    def test_deferred_move_books_cogs_once_when_it_is_finally_posted(self):
        today = fields.Date.context_today(self.env.user)
        accounting_date = today + timedelta(days=30)
        invoice = self._out_invoice(accounting_date)

        invoice._post(soft=True)
        self.assertEqual(invoice.state, "draft")
        # what _autopost_draft_entries does once the accounting date arrives,
        # without its cron bookkeeping (which commits, and tests may not)
        with freeze_time(accounting_date):
            invoice._post(soft=True)

        self.assertEqual(invoice.state, "posted")
        cogs = self._cogs(invoice)
        self.assertEqual(len(cogs), 2, "COGS lines were created twice")
        self.assertEqual(
            sum(cogs.mapped("debit")),
            self.product_standard_auto.standard_price,
            "COGS was booked for more than the cost of the goods",
        )

    def test_soft_post_returns_only_the_moves_it_posted(self):
        today = fields.Date.context_today(self.env.user)
        same_day = self._out_invoice(today)
        future = self._out_invoice(today + timedelta(days=30))

        posted = (same_day | future)._post(soft=True)

        self.assertEqual(posted, same_day)
        self.assertLessEqual(
            len(posted - (same_day | future)),
            0,
            "_post returned records that were never in self",
        )
