from datetime import timedelta

from odoo import Command, fields
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestAbnormalDateAnchor(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(
            context={**cls.env.context, "disable_abnormal_invoice_detection": False}
        )

    def _bill_vals(self, invoice_date=False, date=None):
        vals = {
            "move_type": "in_invoice",
            "partner_id": self.partner_a.id,
            "invoice_date": invoice_date,
            "line_ids": [
                Command.create(
                    {"name": "product", "price_unit": 100, "tax_ids": [Command.clear()]}
                )
            ],
        }
        if date is not None:
            vals["date"] = date
        return vals

    def _monthly_history(self):
        today = fields.Date.context_today(self.env["account.move"])
        start = today - timedelta(days=30 * 31)
        bills = self.env["account.move"].create(
            [
                self._bill_vals(invoice_date=start + timedelta(days=30 * i))
                for i in range(31)
            ]
        )
        bills.action_post()
        return max(bills.mapped("invoice_date"))

    def test_abnormal_date_flagged_when_invoice_date_is_set(self):
        too_soon = self._monthly_history() + timedelta(days=5)
        bill = self.env["account.move"].create(
            self._bill_vals(invoice_date=too_soon, date=too_soon)
        )
        self.assertTrue(
            bill.abnormal_date_warning,
            "five days into a thirty-day cadence is the anomaly this warns about",
        )

    def test_abnormal_date_flagged_when_only_date_is_set(self):
        too_soon = self._monthly_history() + timedelta(days=5)
        bill = self.env["account.move"].create(
            self._bill_vals(invoice_date=False, date=too_soon)
        )
        self.assertFalse(bill.invoice_date)
        self.assertEqual(bill.date, too_soon)
        self.assertTrue(
            bill.abnormal_date_warning,
            "a bill whose only date is `date` must be judged against `date`, the "
            "anchor its own SQL window used",
        )


@tagged("post_install", "-at_install")
class TestPaymentReferenceFollowsTheNumber(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.other_sale_journal = cls.company_data["default_journal_sale"].copy(
            {"name": "Second Sale Journal", "code": "SAJ2"}
        )

    def _invoice(self, **extra):
        return self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": self.partner_a.id,
                "invoice_date": "2026-06-01",
                "journal_id": self.company_data["default_journal_sale"].id,
                "line_ids": [
                    Command.create(
                        {
                            "name": "product",
                            "price_unit": 100,
                            "tax_ids": [Command.clear()],
                        }
                    )
                ],
                **extra,
            }
        )

    def _term_line(self, move):
        return move.line_ids.filtered(lambda line: line.display_type == "payment_term")

    def test_computed_reference_follows_a_journal_change(self):
        invoice = self._invoice()
        invoice.action_post()
        self.assertEqual(invoice.payment_reference, invoice.name)

        invoice.action_draft()
        invoice.write({"name": "/", "journal_id": self.other_sale_journal.id})
        invoice.action_post()

        self.assertEqual(
            invoice.payment_reference,
            invoice.name,
            "the reference was computed from the old number and must be recomputed "
            "from the new one, not left quoting a number that is gone",
        )
        self.assertEqual(
            self._term_line(invoice).name,
            invoice.name,
            "the payment term item labels itself from the move's payment reference",
        )

    def test_computed_reference_survives_an_unchanged_number(self):
        invoice = self._invoice()
        invoice.action_post()
        reference = invoice.payment_reference

        invoice.action_draft()
        invoice.write({"name": "/"})
        invoice.action_post()

        self.assertEqual(invoice.payment_reference, reference)
        self.assertEqual(invoice.payment_reference, invoice.name)

    def test_user_reference_is_never_discarded(self):
        invoice = self._invoice(payment_reference="CUSTOMER-REF-42")
        invoice.action_post()
        self.assertEqual(invoice.payment_reference, "CUSTOMER-REF-42")

        invoice.action_draft()
        invoice.write({"name": "/", "journal_id": self.other_sale_journal.id})
        invoice.action_post()

        self.assertEqual(
            invoice.payment_reference,
            "CUSTOMER-REF-42",
            "renumbering must not touch a reference the compute did not write",
        )
