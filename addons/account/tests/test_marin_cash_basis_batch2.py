from odoo import Command
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestMarinCashBasisBatch2(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.company_data["company"]
        cls.company.account_config_id.tax_exigibility = True
        cls.receivable_account = cls.company_data["default_account_receivable"]
        cls.revenue_account = cls.company_data["default_account_revenue"]
        cls.bank_account = cls.company_data["default_journal_bank"].default_account_id
        cls.transition_account = cls.env["account.account"].create(
            {
                "code": "caba.transition",
                "name": "caba_transition",
                "account_type": "income",
                "reconcile": True,
            }
        )
        cls.tax_account = cls.env["account.account"].create(
            {"code": "caba.tax", "name": "caba_tax", "account_type": "income"}
        )
        cls.caba_tax = cls.env["account.tax"].create(
            {
                "name": "caba_third",
                "amount": 33.3333,
                "company_ids": [Command.set(cls.company.ids)],
                "cash_basis_transition_account_id": cls.transition_account.id,
                "tax_exigibility": "on_payment",
                "invoice_repartition_line_ids": [
                    Command.create({"repartition_type": "base"}),
                    Command.create(
                        {
                            "repartition_type": "tax",
                            "account_id": cls.tax_account.id,
                        }
                    ),
                ],
                "refund_repartition_line_ids": [
                    Command.create({"repartition_type": "base"}),
                    Command.create(
                        {
                            "repartition_type": "tax",
                            "account_id": cls.tax_account.id,
                        }
                    ),
                ],
            }
        )
        cls.caba_tax_repartition = cls.caba_tax.invoice_repartition_line_ids.filtered(
            lambda line: line.repartition_type == "tax"
        )
        cls.other_currency = cls.setup_other_currency("EUR")
        cls.third_currency = cls.setup_other_currency(
            "CAD", rates=[("2016-01-01", 6.0), ("2017-01-01", 4.0)]
        )

    def _receivable_vals(self, balance, **extra):
        return {
            "account_id": self.receivable_account.id,
            "partner_id": self.partner_a.id,
            "date_maturity": "2025-01-01",
            "balance": balance,
            **extra,
        }

    def _sale_lines_vals(self):
        return [
            {
                "account_id": self.revenue_account.id,
                "balance": -100.0,
                "tax_ids": [Command.set(self.caba_tax.ids)],
            },
            {
                "account_id": self.transition_account.id,
                "balance": -33.33,
                "tax_repartition_line_id": self.caba_tax_repartition.id,
            },
        ]

    def _post_entry(self, lines_vals, date="2025-01-01"):
        move = self.env["account.move"].create(
            {
                "move_type": "entry",
                "date": date,
                "line_ids": [Command.create(vals) for vals in lines_vals],
            }
        )
        move.action_post()
        return move

    def _receivable_lines(self, move):
        return move.line_ids.filtered(
            lambda line: line.account_id == self.receivable_account
        ).sorted("balance")

    def _exigible_amounts(self, move):
        caba_lines = self.env["account.move.line"].search(
            [
                "|",
                ("move_id.tax_cash_basis_origin_move_id", "=", move.id),
                (
                    "move_id.reversed_entry_id.tax_cash_basis_origin_move_id",
                    "=",
                    move.id,
                ),
                ("parent_state", "=", "posted"),
            ]
        )
        base_lines = caba_lines.filtered(
            lambda line: line.tax_ids and not line.tax_repartition_line_id
        )
        tax_lines = caba_lines.filtered("tax_repartition_line_id")
        return (
            round(-sum(base_lines.mapped("balance")), 2),
            round(-sum(tax_lines.mapped("balance")), 2),
        )

    def test_same_move_settlement_makes_the_whole_tax_exigible(self):
        move = self._post_entry(
            [
                *self._sale_lines_vals(),
                self._receivable_vals(133.33),
                self._receivable_vals(-133.33),
                {"account_id": self.bank_account.id, "balance": 133.33},
            ]
        )
        self._receivable_lines(move).reconcile()

        self.assertTrue(all(self._receivable_lines(move).mapped("reconciled")))
        self.assertEqual(self._exigible_amounts(move), (100.0, 33.33))
        transition_line = move.line_ids.filtered(
            lambda line: line.account_id == self.transition_account
        )
        self.assertTrue(transition_line.reconciled)

    def test_same_move_netting_counts_each_side_once(self):
        move = self._post_entry(
            [
                *self._sale_lines_vals(),
                self._receivable_vals(183.33),
                self._receivable_vals(-50.0),
            ]
        )
        credit_line, debit_line = self._receivable_lines(move)
        (credit_line + debit_line).reconcile()

        self.assertEqual(self._exigible_amounts(move), (42.86, 14.28))

        payment = self._post_entry(
            [
                self._receivable_vals(-133.33),
                {"account_id": self.bank_account.id, "balance": 133.33},
            ]
        )
        (debit_line + self._receivable_lines(payment)).reconcile()

        self.assertTrue(debit_line.reconciled)
        self.assertEqual(self._exigible_amounts(move), (100.0, 33.33))

    def test_same_move_unreconcile_reverses_its_cash_basis_entries(self):
        move = self._post_entry(
            [
                *self._sale_lines_vals(),
                self._receivable_vals(133.33),
                self._receivable_vals(-133.33),
                {"account_id": self.bank_account.id, "balance": 133.33},
            ]
        )
        receivable_lines = self._receivable_lines(move)
        receivable_lines.reconcile()
        self.assertEqual(self._exigible_amounts(move), (100.0, 33.33))

        receivable_lines.remove_move_reconcile()

        self.assertEqual(self._exigible_amounts(move), (0.0, 0.0))
        transition_line = move.line_ids.filtered(
            lambda line: line.account_id == self.transition_account
        )
        self.assertAlmostEqual(transition_line.amount_residual, -33.33)

    def test_exchange_moves_link_to_their_own_partial(self):
        count = 50
        invoice = self._post_entry(
            [
                *(
                    self._receivable_vals(
                        100.0 + index,
                        amount_currency=3 * (100.0 + index),
                        currency_id=self.other_currency.id,
                    )
                    for index in range(count)
                ),
                {
                    "account_id": self.revenue_account.id,
                    "balance": -sum(100.0 + index for index in range(count)),
                },
            ],
            date="2016-01-01",
        )
        payment = self._post_entry(
            [
                *(
                    self._receivable_vals(
                        -1.5 * (100.0 + index),
                        amount_currency=-3 * (100.0 + index),
                        currency_id=self.other_currency.id,
                    )
                    for index in range(count)
                ),
                {
                    "account_id": self.bank_account.id,
                    "balance": sum(1.5 * (100.0 + index) for index in range(count)),
                },
            ],
            date="2017-01-01",
        )
        invoice_lines = self._receivable_lines(invoice).sorted("amount_currency")
        payment_lines = self._receivable_lines(payment).sorted(
            "amount_currency", reverse=True
        )

        self.env["account.move.line"]._reconcile_plan(
            [
                debit_line + credit_line
                for debit_line, credit_line in zip(
                    invoice_lines, payment_lines, strict=True
                )
            ]
        )

        partials = invoice_lines.matched_credit_ids.filtered(
            lambda partial: partial.credit_move_id in payment_lines
        )
        self.assertEqual(len(partials), count)
        self.assertEqual(len(partials.exchange_move_id), count)
        for partial in partials:
            exchange_receivable = partial.exchange_move_id.line_ids.filtered(
                lambda line: line.account_id == self.receivable_account
            )
            self.assertEqual(len(exchange_receivable), 1)
            fixed_line = (
                exchange_receivable.matched_credit_ids.credit_move_id
                | exchange_receivable.matched_debit_ids.debit_move_id
            )
            self.assertEqual(len(fixed_line), 1)
            self.assertIn(fixed_line, partial.debit_move_id | partial.credit_move_id)
            self.assertAlmostEqual(
                abs(exchange_receivable.balance), 0.5 * partial.debit_move_id.balance
            )
        self.assertTrue(all((invoice_lines | payment_lines).mapped("reconciled")))

    def _transition_line(self, move):
        return move.line_ids.filtered(
            lambda line: line.account_id == self.transition_account
        )

    def _post_mixed_currency_sale(self, receivables_vals, currency=None, rate=1.0):
        currency = currency or self.company.currency_id
        return self._post_entry(
            [
                *receivables_vals,
                {
                    "account_id": self.revenue_account.id,
                    "currency_id": currency.id,
                    "amount_currency": -100.0 * rate,
                    "balance": -100.0,
                    "tax_ids": [Command.set(self.caba_tax.ids)],
                },
                {
                    "account_id": self.transition_account.id,
                    "currency_id": currency.id,
                    "amount_currency": -33.33 * rate,
                    "balance": -33.33,
                    "tax_repartition_line_id": self.caba_tax_repartition.id,
                },
            ],
            date="2016-01-01",
        )

    def _pay(self, move_line, amount_currency, balance):
        payment = self._post_entry(
            [
                self._receivable_vals(
                    -balance,
                    amount_currency=-amount_currency,
                    currency_id=move_line.currency_id.id,
                ),
                {"account_id": self.bank_account.id, "balance": balance},
            ],
            date="2017-01-01",
        )
        (move_line + self._receivable_lines(payment)).reconcile()
        return payment

    def test_foreign_receivable_with_company_currency_taxes_full_payment(self):
        move = self._post_mixed_currency_sale(
            [
                self._receivable_vals(
                    133.33, amount_currency=400.0, currency_id=self.other_currency.id
                )
            ]
        )
        self.assertFalse(move.always_tax_exigible)
        self.assertEqual(self._exigible_amounts(move), (0.0, 0.0))

        self._pay(self._receivable_lines(move), 400.0, 200.0)

        self.assertEqual(self._exigible_amounts(move), (100.0, 33.33))
        self.assertTrue(self._transition_line(move).reconciled)

    def test_foreign_receivable_with_company_currency_taxes_partial_payments(self):
        move = self._post_mixed_currency_sale(
            [
                self._receivable_vals(
                    133.33, amount_currency=400.0, currency_id=self.other_currency.id
                )
            ]
        )
        receivable_line = self._receivable_lines(move)

        self._pay(receivable_line, 200.0, 100.0)

        base, tax = self._exigible_amounts(move)
        self.assertEqual(base, 50.0)
        self.assertAlmostEqual(tax, 16.67, delta=0.011)
        self.assertFalse(self._transition_line(move).reconciled)

        self._pay(receivable_line, 200.0, 100.0)

        self.assertEqual(self._exigible_amounts(move), (100.0, 33.33))
        self.assertTrue(self._transition_line(move).reconciled)

    def test_receivables_in_two_currencies_fall_back_to_company_currency(self):
        move = self._post_mixed_currency_sale(
            [
                self._receivable_vals(
                    100.0, amount_currency=300.0, currency_id=self.other_currency.id
                ),
                self._receivable_vals(33.33),
            ]
        )
        self.assertFalse(move.always_tax_exigible)
        receivable_eur, receivable_usd = self._receivable_lines(move).sorted(
            lambda line: line.currency_id != self.other_currency
        )

        self._pay(receivable_eur, 300.0, 150.0)

        self.assertEqual(self._exigible_amounts(move), (75.0, 25.0))

        self._pay(receivable_usd, 33.33, 33.33)

        self.assertEqual(self._exigible_amounts(move), (100.0, 33.33))
        self.assertTrue(self._transition_line(move).reconciled)

    def test_taxes_in_a_third_currency_are_valued_at_the_payment_date_rate(self):
        move = self._post_mixed_currency_sale(
            [
                self._receivable_vals(
                    133.33, amount_currency=400.0, currency_id=self.other_currency.id
                )
            ],
            currency=self.third_currency,
            rate=6.0,
        )

        self._pay(self._receivable_lines(move), 400.0, 200.0)

        self.assertEqual(self._exigible_amounts(move), (150.0, 50.0))
        self.assertTrue(self._transition_line(move).reconciled)

    def _draft_entry(self, lines_vals):
        return self.env["account.move"].create(
            {
                "move_type": "entry",
                "date": "2025-01-01",
                "line_ids": [Command.create(vals) for vals in lines_vals],
            }
        )

    def test_always_tax_exigible_follows_a_tax_added_to_a_draft_line(self):
        zero_caba_tax = self.caba_tax.copy({"name": "caba_zero", "amount": 0.0})
        move = self._draft_entry(
            [
                self._receivable_vals(100.0),
                {"account_id": self.revenue_account.id, "balance": -100.0},
            ]
        )
        self.assertTrue(move.always_tax_exigible)
        revenue_line = move.line_ids.filtered(
            lambda line: line.account_id == self.revenue_account
        )
        line_count = len(move.line_ids)

        revenue_line.tax_ids = zero_caba_tax

        self.assertEqual(len(move.line_ids), line_count)
        self.assertFalse(move.always_tax_exigible)

        revenue_line.tax_ids = False

        self.assertTrue(move.always_tax_exigible)

    def test_posted_entry_keeps_always_tax_exigible_when_an_account_changes_type(self):
        receivable = self.receivable_account.copy({"code": "caba.rec"})
        move = self._post_entry(
            [
                *self._sale_lines_vals(),
                self._receivable_vals(133.33, account_id=receivable.id),
            ]
        )
        self.assertFalse(move.always_tax_exigible)

        receivable.account_type = "asset_current"

        self.assertFalse(move.always_tax_exigible)
