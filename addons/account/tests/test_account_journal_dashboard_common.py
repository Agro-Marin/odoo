from odoo import Command
from odoo.tests import tagged
from odoo.tools.misc import format_amount

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestAccountJournalDashboardCommon(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.other_currency = cls.setup_other_currency("EUR")

    def _create_test_vendor_bills(self, journal):
        twentyfive_now_term = self.env["account.payment.term"].create(
            {
                "name": "25% now, rest in 30 days",
                "note": "Pay 25% on invoice date and 75% 30 days later",
                "line_ids": [
                    Command.create(
                        {
                            "value": "percent",
                            "value_amount": 25.00,
                            "delay_type": "days_after",
                            "nb_days": 0,
                        }
                    ),
                    Command.create(
                        {
                            "value": "percent",
                            "value_amount": 75.00,
                            "delay_type": "days_after",
                            "nb_days": 30,
                        }
                    ),
                ],
            }
        )

        self.env["account.move"].create(
            {
                "move_type": "in_invoice",
                "journal_id": journal.id,
                "partner_id": self.partner_a.id,
                "invoice_date": "2023-04-01",
                "date": "2023-03-15",
                "invoice_payment_term_id": twentyfive_now_term.id,
                "invoice_line_ids": [
                    Command.create(
                        {
                            "product_id": self.product_a.id,
                            "quantity": 1,
                            "name": "product test 1",
                            "price_unit": 4000,
                            "tax_ids": [],
                        }
                    )
                ],
            }
        ).action_post()

        self.env["account.move"].create(
            {
                "move_type": "in_invoice",
                "journal_id": journal.id,
                "partner_id": self.partner_a.id,
                "invoice_date": "2023-03-01",
                "date": "2023-03-15",
                "invoice_payment_term_id": twentyfive_now_term.id,
                "invoice_line_ids": [
                    Command.create(
                        {
                            "product_id": self.product_a.id,
                            "quantity": 1,
                            "name": "product test 1",
                            "price_unit": 400,
                            "tax_ids": [],
                        }
                    )
                ],
            }
        ).action_post()

        self.env["account.move"].create(
            {
                "move_type": "in_invoice",
                "journal_id": journal.id,
                "partner_id": self.partner_a.id,
                "invoice_date": "2023-02-01",
                "date": "2023-03-15",
                "invoice_payment_term_id": twentyfive_now_term.id,
                "invoice_line_ids": [
                    Command.create(
                        {
                            "product_id": self.product_a.id,
                            "quantity": 1,
                            "name": "product test 1",
                            "price_unit": 40,
                            "tax_ids": [],
                        }
                    )
                ],
            }
        ).action_post()

    def assertDashboardPurchaseSaleData(
        self,
        journal,
        number_draft,
        sum_draft,
        number_waiting,
        sum_waiting,
        number_late,
        sum_late,
        currency,
        **kwargs,
    ):
        expected_values = {
            "number_draft": number_draft,
            "sum_draft": format_amount(self.env, sum_draft, currency),
            "number_waiting": number_waiting,
            "sum_waiting": format_amount(self.env, sum_waiting, currency),
            "number_late": number_late,
            "sum_late": format_amount(self.env, sum_late, currency),
            **kwargs,
        }
        dashboard_data = journal._get_journal_dashboard_data_batched()[journal.id]
        self.assertDictEqual({**dashboard_data, **expected_values}, dashboard_data)
