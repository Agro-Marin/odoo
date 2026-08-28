from lxml import etree

from odoo import Command
from odoo.tests import tagged
from odoo.tools.safe_eval import safe_eval

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestAccountMovePaymentsWidget(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.receivable_account = cls.company_data["default_account_receivable"]
        cls.payable_account = cls.company_data["default_account_payable"]

        cls.curr_1 = cls.company_data["currency"]
        cls.curr_2 = cls.setup_other_currency("EUR")
        cls.curr_3 = cls.setup_other_currency(
            "CAD", rates=[("2016-01-01", 6.0), ("2017-01-01", 4.0)]
        )

        cls.payment_2016_curr_1 = cls.env["account.move"].create(
            {
                "date": "2016-01-01",
                "line_ids": [
                    (
                        0,
                        0,
                        {
                            "debit": 0.0,
                            "credit": 500.0,
                            "amount_currency": -500.0,
                            "currency_id": cls.curr_1.id,
                            "account_id": cls.receivable_account.id,
                            "partner_id": cls.partner_a.id,
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "debit": 500.0,
                            "credit": 0.0,
                            "amount_currency": 500.0,
                            "currency_id": cls.curr_1.id,
                            "account_id": cls.payable_account.id,
                            "partner_id": cls.partner_a.id,
                        },
                    ),
                ],
            }
        )
        cls.payment_2016_curr_1.action_post()

        cls.payment_2016_curr_2 = cls.env["account.move"].create(
            {
                "date": "2016-01-01",
                "line_ids": [
                    (
                        0,
                        0,
                        {
                            "debit": 0.0,
                            "credit": 500.0,
                            "amount_currency": -1550.0,
                            "currency_id": cls.curr_2.id,
                            "account_id": cls.receivable_account.id,
                            "partner_id": cls.partner_a.id,
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "debit": 500.0,
                            "credit": 0.0,
                            "amount_currency": 1550.0,
                            "currency_id": cls.curr_2.id,
                            "account_id": cls.payable_account.id,
                            "partner_id": cls.partner_a.id,
                        },
                    ),
                ],
            }
        )
        cls.payment_2016_curr_2.action_post()

        cls.payment_2017_curr_2 = cls.env["account.move"].create(
            {
                "date": "2017-01-01",
                "line_ids": [
                    (
                        0,
                        0,
                        {
                            "debit": 0.0,
                            "credit": 500.0,
                            "amount_currency": -950.0,
                            "currency_id": cls.curr_2.id,
                            "account_id": cls.receivable_account.id,
                            "partner_id": cls.partner_a.id,
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "debit": 500.0,
                            "credit": 0.0,
                            "amount_currency": 950.0,
                            "currency_id": cls.curr_2.id,
                            "account_id": cls.payable_account.id,
                            "partner_id": cls.partner_a.id,
                        },
                    ),
                ],
            }
        )
        cls.payment_2017_curr_2.action_post()

        cls.payment_2016_curr_3 = cls.env["account.move"].create(
            {
                "date": "2016-01-01",
                "line_ids": [
                    (
                        0,
                        0,
                        {
                            "debit": 0.0,
                            "credit": 500.0,
                            "amount_currency": -3050.0,
                            "currency_id": cls.curr_3.id,
                            "account_id": cls.receivable_account.id,
                            "partner_id": cls.partner_a.id,
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "debit": 500.0,
                            "credit": 0.0,
                            "amount_currency": 3050.0,
                            "currency_id": cls.curr_3.id,
                            "account_id": cls.payable_account.id,
                            "partner_id": cls.partner_a.id,
                        },
                    ),
                ],
            }
        )
        cls.payment_2016_curr_3.action_post()

        cls.payment_2017_curr_3 = cls.env["account.move"].create(
            {
                "date": "2017-01-01",
                "line_ids": [
                    (
                        0,
                        0,
                        {
                            "debit": 0.0,
                            "credit": 500.0,
                            "amount_currency": -1950.0,
                            "currency_id": cls.curr_3.id,
                            "account_id": cls.receivable_account.id,
                            "partner_id": cls.partner_a.id,
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "debit": 500.0,
                            "credit": 0.0,
                            "amount_currency": 1950.0,
                            "currency_id": cls.curr_3.id,
                            "account_id": cls.payable_account.id,
                            "partner_id": cls.partner_a.id,
                        },
                    ),
                ],
            }
        )
        cls.payment_2017_curr_3.action_post()

    def test_outstanding_payments_single_currency(self):
        out_invoice = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "date": "2017-01-01",
                "invoice_date": "2017-01-01",
                "partner_id": self.partner_a.id,
                "currency_id": self.curr_1.id,
                "invoice_line_ids": [(0, 0, {"name": "/", "price_unit": 2500.0})],
            }
        )
        out_invoice.action_post()

        in_invoice = self.env["account.move"].create(
            {
                "move_type": "in_invoice",
                "date": "2017-01-01",
                "invoice_date": "2017-01-01",
                "partner_id": self.partner_a.id,
                "currency_id": self.curr_1.id,
                "invoice_line_ids": [(0, 0, {"name": "/", "price_unit": 2500.0})],
            }
        )
        in_invoice.action_post()

        expected_amounts = {
            self.payment_2016_curr_1.id: 500.0,
            self.payment_2016_curr_2.id: 500.0,
            self.payment_2017_curr_2.id: 500.0,
            self.payment_2016_curr_3.id: 500.0,
            self.payment_2017_curr_3.id: 500.0,
        }

        self.assert_invoice_outstanding_to_reconcile_widget(
            out_invoice, expected_amounts
        )
        self.assert_invoice_outstanding_to_reconcile_widget(
            in_invoice, expected_amounts
        )

    def test_outstanding_payments_foreign_currency(self):
        out_invoice = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "date": "2017-01-01",
                "invoice_date": "2017-01-01",
                "partner_id": self.partner_a.id,
                "currency_id": self.curr_2.id,
                "invoice_line_ids": [(0, 0, {"name": "/", "price_unit": 7500.0})],
            }
        )
        out_invoice.action_post()

        in_invoice = self.env["account.move"].create(
            {
                "move_type": "in_invoice",
                "date": "2017-01-01",
                "invoice_date": "2017-01-01",
                "partner_id": self.partner_a.id,
                "currency_id": self.curr_2.id,
                "invoice_line_ids": [(0, 0, {"name": "/", "price_unit": 7500.0})],
            }
        )
        in_invoice.action_post()

        expected_amounts = {
            self.payment_2016_curr_1.id: 1500.0,
            self.payment_2016_curr_2.id: 1550.0,
            self.payment_2017_curr_2.id: 950.0,
            self.payment_2016_curr_3.id: 1500.0,
            self.payment_2017_curr_3.id: 1000.0,
        }

        self.assert_invoice_outstanding_to_reconcile_widget(
            out_invoice, expected_amounts
        )
        self.assert_invoice_outstanding_to_reconcile_widget(
            in_invoice, expected_amounts
        )

    def test_payments_with_exchange_difference_payment(self):
        out_invoice = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "date": "2016-01-01",
                "invoice_date": "2016-01-01",
                "partner_id": self.partner_a.id,
                "currency_id": self.curr_2.id,
                "invoice_line_ids": [
                    Command.create(
                        {
                            "product_id": self.product_a.id,
                            "price_unit": 300,
                            "tax_ids": [],
                        }
                    )
                ],
            }
        )
        out_invoice.action_post()

        payment = (
            self.env["account.payment.register"]
            .with_context(active_model="account.move", active_ids=out_invoice.ids)
            .create({"payment_date": "2017-01-01"})
            ._create_payments()
        )

        expected_amounts = {payment.move_id.id: 300.0}
        for ln in out_invoice.line_ids:
            if ln.matched_credit_ids.exchange_move_id:
                expected_amounts[ln.matched_credit_ids.exchange_move_id.id] = 50.0

        self.assert_invoice_outstanding_reconciled_widget(out_invoice, expected_amounts)

    def test_payments_with_exchange_difference_invoice(self):
        out_invoice = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "date": "2017-01-01",
                "invoice_date": "2017-01-01",
                "partner_id": self.partner_a.id,
                "currency_id": self.curr_2.id,
                "invoice_line_ids": [
                    Command.create(
                        {
                            "product_id": self.product_a.id,
                            "price_unit": 300,
                            "tax_ids": [],
                        }
                    )
                ],
            }
        )
        out_invoice.action_post()

        payment = (
            self.env["account.payment.register"]
            .with_context(active_model="account.move", active_ids=out_invoice.ids)
            .create({"payment_date": "2016-01-01"})
            ._create_payments()
        )

        expected_amounts = {payment.move_id.id: 300.0}
        for ln in out_invoice.line_ids:
            if ln.matched_credit_ids.exchange_move_id:
                expected_amounts[ln.matched_credit_ids.exchange_move_id.id] = 50.0

        self.assert_invoice_outstanding_reconciled_widget(out_invoice, expected_amounts)

    def test_outstanding_widget_shown_on_draft_invoice(self):
        """The outstanding credits/debits must show on draft invoices too.

        `_compute_invoice_outstanding_credits_debits_widget` already accepts
        `state in {"draft", "posted"}`, so the widget is computed for a draft
        invoice and then thrown away by the form view.
        """
        out_invoice = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "date": "2017-01-01",
                "invoice_date": "2017-01-01",
                "partner_id": self.partner_a.id,
                "currency_id": self.curr_1.id,
                "invoice_line_ids": [
                    Command.create({"name": "/", "price_unit": 2500.0})
                ],
            }
        )
        self.assertEqual(out_invoice.state, "draft")
        self.assertTrue(
            out_invoice.invoice_has_outstanding,
            "the backend already offers the outstanding payments on a draft invoice",
        )

        record_values = {
            "state": out_invoice.state,
            "move_type": out_invoice.move_type,
            "payment_state": out_invoice.payment_state,
            "invoice_has_outstanding": out_invoice.invoice_has_outstanding,
        }
        arch = etree.fromstring(self.env.ref("account.view_move_form").arch)
        outstanding_nodes = [
            node
            for node in arch.iter()
            if node.tag != "button"
            and "invoice_has_outstanding" in (node.get("invisible") or "")
        ]
        self.assertEqual(
            len(outstanding_nodes),
            5,
            "4 alerts (one per move type) and the group holding the widget",
        )
        shown = [
            node
            for node in outstanding_nodes
            if not safe_eval(node.get("invisible"), record_values)
        ]
        self.assertEqual(
            len(shown),
            2,
            "on a draft customer invoice: the 'outstanding credits' alert and the"
            " widget group; the 3 alerts of the other move types stay hidden",
        )

        # The two "Pay" buttons also read `invoice_has_outstanding`, but
        # registering a payment still requires a posted move: they must keep
        # their `state != 'posted'` guard.
        pay_buttons = [
            node
            for node in arch.iter("button")
            if "invoice_has_outstanding" in (node.get("invisible") or "")
        ]
        self.assertEqual(len(pay_buttons), 2)
        for button in pay_buttons:
            with self.subTest(button=button.get("id")):
                self.assertTrue(safe_eval(button.get("invisible"), record_values))
