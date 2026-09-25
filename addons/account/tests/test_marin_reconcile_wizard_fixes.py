from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import new_test_user, tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.addons.account.tests.common_report_engine import TestAccountReportsCommon


@tagged("post_install", "-at_install")
class TestMarinReconcileWizardFixes(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.company_data["company"]
        cls.misc_journal = cls.company_data["default_journal_misc"]
        cls.receivable_account = cls.company_data["default_account_receivable"]
        cls.payable_account = cls.company_data["default_account_payable"]
        cls.revenue_account = cls.company_data["default_account_revenue"]
        cls.analytic_plan = cls.env["account.analytic.plan"].create(
            {"name": "Marin Fixes Plan"}
        )
        cls.analytic_account = cls.env["account.analytic.account"].create(
            {"name": "Marin Fixes AA", "plan_id": cls.analytic_plan.id}
        )

    def _misc_move(self, lines):
        move = self.env["account.move"].create(
            {
                "move_type": "entry",
                "date": "2017-01-01",
                "journal_id": self.misc_journal.id,
                "line_ids": [Command.create(vals) for vals in lines],
            }
        )
        move.action_post()
        return move

    def test_change_period_reconciles_every_accrual_line_with_one_line_per_move(self):
        invoices = self.env["account.move"]
        for invoice_date in ("2017-01-01", "2017-02-01"):
            invoices += self.init_invoice(
                "out_invoice",
                partner=self.partner_a,
                invoice_date=invoice_date,
                amounts=[1000.0],
                taxes=[],
                post=True,
            )
        accrual_account = self.env["account.account"].create(
            {
                "name": "Accrual Revenue",
                "code": "ACCR.MARIN",
                "account_type": "liability_current",
                "reconcile": True,
            }
        )
        wizard = (
            self.env["account.automatic.entry.wizard"]
            .with_context(
                active_model="account.move.line",
                active_ids=invoices.invoice_line_ids.ids,
            )
            .create(
                {
                    "action": "change_period",
                    "date": "2018-01-01",
                    "journal_id": self.misc_journal.id,
                    "revenue_accrual_account": accrual_account.id,
                    "expense_accrual_account": accrual_account.id,
                }
            )
        )
        action = wizard.do_action()
        created_moves = self.env["account.move"].search(action["domain"])
        accrual_lines = created_moves.line_ids.filtered(
            lambda line: line.account_id == accrual_account
        )
        self.assertEqual(len(accrual_lines), 4)
        self.assertRecordValues(
            accrual_lines, [{"reconciled": True, "amount_residual": 0.0}] * 4
        )

    def test_change_account_reconciles_destination_lines_once_across_partners(self):
        source_account = self.env["account.account"].create(
            {
                "name": "Transfer Source",
                "code": "SRC.MARIN",
                "account_type": "asset_current",
            }
        )
        destination_lines = self.env["account.move.line"]
        source_lines = self.env["account.move.line"]
        for partner in (self.partner_a, self.partner_b):
            move = self._misc_move(
                [
                    {
                        "account_id": self.receivable_account.id,
                        "partner_id": partner.id,
                        "balance": -100.0,
                    },
                    {
                        "account_id": source_account.id,
                        "partner_id": partner.id,
                        "balance": 100.0,
                    },
                ]
            )
            destination_lines += move.line_ids.filtered(
                lambda line: line.account_id == self.receivable_account
            )
            source_lines += move.line_ids.filtered(
                lambda line: line.account_id == source_account
            )
        wizard = (
            self.env["account.automatic.entry.wizard"]
            .with_context(
                active_model="account.move.line",
                active_ids=(destination_lines + source_lines).ids,
            )
            .create(
                {
                    "action": "change_account",
                    "date": "2017-01-01",
                    "journal_id": self.misc_journal.id,
                    "destination_account_id": self.receivable_account.id,
                }
            )
        )
        action = wizard.do_action()
        new_destination_lines = (
            self.env["account.move"]
            .browse(action["res_id"])
            .line_ids.filtered(lambda line: line.account_id == self.receivable_account)
        )
        self.assertRecordValues(
            destination_lines + new_destination_lines,
            [{"reconciled": True, "amount_residual": 0.0}] * 4,
        )

    def test_revaluation_wizard_non_manager_cannot_change_company_defaults(self):
        config = self.company.account_config_id
        journal = self.misc_journal.copy()
        account = self.company_data["default_account_expense"].copy()
        before = (
            config.account_revaluation_journal_id,
            config.account_revaluation_expense_provision_account_id,
            config.account_revaluation_income_provision_account_id,
        )
        users = {
            "non_manager": new_test_user(
                self.env,
                login="marin_reval_user",
                groups="account.group_account_user",
                company_id=self.company.id,
            ),
            "manager": new_test_user(
                self.env,
                login="marin_reval_manager",
                groups="account.group_account_user,account.group_account_manager",
                company_id=self.company.id,
            ),
        }

        def run_inverses(user):
            wizard = (
                self.env["account.multicurrency.revaluation.wizard"]
                .with_user(user)
                .new(
                    {
                        "company_id": self.company.id,
                        "journal_id": journal.id,
                        "expense_provision_account_id": account.id,
                        "income_provision_account_id": account.id,
                    }
                )
            )
            wizard._inverse_journal_id()
            wizard._inverse_expense_provision_account_id()
            wizard._inverse_income_provision_account_id()

        run_inverses(users["non_manager"])
        config.invalidate_recordset()
        self.assertEqual(
            (
                config.account_revaluation_journal_id,
                config.account_revaluation_expense_provision_account_id,
                config.account_revaluation_income_provision_account_id,
            ),
            before,
        )

        run_inverses(users["manager"])
        config.invalidate_recordset()
        self.assertRecordValues(
            config,
            [
                {
                    "account_revaluation_journal_id": journal.id,
                    "account_revaluation_expense_provision_account_id": account.id,
                    "account_revaluation_income_provision_account_id": account.id,
                }
            ],
        )

    def _discount_invoice(self, lines):
        self.company.account_config_id.account_discount_expense_allocation_id = (
            self.company_data["default_account_expense"].copy()
        )
        return self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": self.partner_a.id,
                "invoice_line_ids": [
                    Command.create(
                        {
                            "name": "line",
                            "account_id": self.revenue_account.id,
                            "quantity": 1,
                            "tax_ids": [],
                            **vals,
                        }
                    )
                    for vals in lines
                ],
            }
        )

    def _discount_distributions(self, invoice):
        return [
            {
                key: round(value, 2)
                for key, value in (line.analytic_distribution or {}).items()
            }
            for line in invoice.line_ids.filtered(
                lambda line: line.display_type == "discount"
            )
        ]

    def test_discount_allocation_keeps_a_partial_analytic_share(self):
        aa = str(self.analytic_account.id)
        invoice = self._discount_invoice(
            [{"price_unit": 100.0, "discount": 10, "analytic_distribution": {aa: 50}}]
        )
        self.assertEqual(self._discount_distributions(invoice), [{aa: 50.0}] * 2)

    def test_discount_allocation_weights_analytic_by_every_line_of_the_key(self):
        aa = str(self.analytic_account.id)
        invoice = self._discount_invoice(
            [
                {
                    "price_unit": 10.0,
                    "discount": 10,
                    "analytic_distribution": {aa: 100},
                },
                {"price_unit": 20.0, "discount": 10},
            ]
        )
        self.assertEqual(self._discount_distributions(invoice), [{aa: 33.33}] * 2)

    def test_discount_allocation_keeps_each_plan_whole(self):
        second_plan_account = self.env["account.analytic.account"].create(
            {
                "name": "Marin Fixes AA 2",
                "plan_id": self.env["account.analytic.plan"]
                .create({"name": "Marin Fixes Plan 2"})
                .id,
            }
        )
        first, second = str(self.analytic_account.id), str(second_plan_account.id)
        invoice = self._discount_invoice(
            [
                {
                    "price_unit": 100.0,
                    "discount": 10,
                    "analytic_distribution": {first: 100, second: 100},
                }
            ]
        )
        self.assertEqual(
            self._discount_distributions(invoice), [{first: 100.0, second: 100.0}] * 2
        )

    def test_change_period_refuses_an_accrual_account_equal_to_the_source(self):
        reconcilable = self.env["account.account"].create(
            {
                "name": "Deferred Revenue",
                "code": "DEFR.MARIN",
                "account_type": "liability_current",
                "reconcile": True,
            }
        )
        move = self._misc_move(
            [
                {"account_id": self.receivable_account.id, "balance": 1000.0},
                {"account_id": reconcilable.id, "balance": -1000.0},
            ]
        )
        wizard = (
            self.env["account.automatic.entry.wizard"]
            .with_context(
                active_model="account.move.line",
                active_ids=move.line_ids.filtered(
                    lambda line: line.account_id == reconcilable
                ).ids,
            )
            .create(
                {
                    "action": "change_period",
                    "date": "2018-01-01",
                    "journal_id": self.misc_journal.id,
                    "revenue_accrual_account": reconcilable.id,
                    "expense_accrual_account": reconcilable.id,
                }
            )
        )
        with self.assertRaisesRegex(UserError, "accrual account"):
            wizard.do_action()

    def _cash_basis_installment_invoice(self, currency=None):
        self.company.account_config_id.tax_exigibility = True
        transition = self.env["account.account"].create(
            {
                "name": "Cash basis transition",
                "code": "CABA.TRANS.MARIN",
                "account_type": "income",
                "reconcile": True,
            }
        )
        tax = self.env["account.tax"].create(
            {
                "name": "Marin cash basis 15%",
                "amount": 15.0,
                "tax_exigibility": "on_payment",
                "cash_basis_transition_account_id": transition.id,
            }
        )
        term = self.env["account.payment.term"].create(
            {
                "name": "Two halves",
                "line_ids": [
                    Command.create(
                        {"value": "percent", "value_amount": 50.0, "nb_days": 0}
                    ),
                    Command.create(
                        {"value": "percent", "value_amount": 50.0, "nb_days": 30}
                    ),
                ],
            }
        )
        invoice = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": self.partner_a.id,
                "invoice_date": "2016-06-01",
                "date": "2016-06-01",
                "currency_id": (currency or self.company.currency_id).id,
                "invoice_payment_term_id": term.id,
                "invoice_line_ids": [
                    Command.create(
                        {
                            "name": "line",
                            "price_unit": 1000.0,
                            "tax_ids": [Command.set(tax.ids)],
                        }
                    )
                ],
            }
        )
        invoice.action_post()
        installments = invoice.line_ids.filtered(
            lambda line: line.account_id == self.receivable_account
        )
        self.assertEqual(len(installments), 2)
        for installment in installments:
            balance = installment.company_currency_id.round(
                installment.balance / 2 if currency else installment.balance
            )
            self._misc_move(
                [
                    {
                        "account_id": self.receivable_account.id,
                        "partner_id": self.partner_a.id,
                        "currency_id": installment.currency_id.id,
                        "amount_currency": -installment.amount_currency,
                        "balance": -balance,
                    },
                    {
                        "account_id": self.company_data[
                            "default_journal_bank"
                        ].default_account_id.id,
                        "currency_id": installment.currency_id.id,
                        "amount_currency": installment.amount_currency,
                        "balance": balance,
                    },
                ]
            )
        return invoice

    def _assert_one_to_one_caba_split_the_tax_in_halves(self, invoice):
        wizard = self.env["account.auto.reconcile.wizard"].new(
            {
                "from_date": "2016-01-01",
                "to_date": "2018-01-01",
                "account_ids": self.receivable_account.ids,
                "partner_ids": self.partner_a.ids,
                "search_mode": "one_to_one",
            }
        )
        wizard.auto_reconcile()
        self.assertEqual(invoice.payment_state, "paid")
        caba_moves = self.env["account.move"].search(
            [("tax_cash_basis_origin_move_id", "=", invoice.id)]
        )
        self.assertEqual(len(caba_moves), 2)
        invoice_tax = abs(
            sum(invoice.line_ids.filtered("tax_line_id").mapped("amount_currency"))
        )
        for caba_move in caba_moves:
            caba_tax = abs(
                sum(
                    caba_move.line_ids.filtered("tax_line_id").mapped("amount_currency")
                )
            )
            self.assertAlmostEqual(caba_tax, invoice_tax / 2)
        return caba_moves

    def test_one_to_one_cash_basis_splits_the_tax_across_installments(self):
        invoice = self._cash_basis_installment_invoice()
        self._assert_one_to_one_caba_split_the_tax_in_halves(invoice)

    def test_one_to_one_cash_basis_splits_the_foreign_tax_across_installments(self):
        currency = self.setup_other_currency(
            "CHF", rates=[("2016-01-01", 1.0), ("2017-01-01", 2.0)]
        )
        invoice = self._cash_basis_installment_invoice(currency=currency)
        caba_moves = self._assert_one_to_one_caba_split_the_tax_in_halves(invoice)
        self.assertEqual(len(set(caba_moves.mapped("amount_total_signed"))), 1)

    def test_split_keeps_the_foreign_amount_of_the_line(self):
        currency = self.setup_other_currency("EUR")
        move = self.env["account.move"].create(
            {
                "move_type": "entry",
                "date": "2019-01-01",
                "line_ids": [
                    Command.create(
                        {
                            "account_id": self.revenue_account.id,
                            "currency_id": currency.id,
                            "amount_currency": 100.0,
                            "balance": 110.0,
                        }
                    ),
                    Command.create(
                        {
                            "account_id": self.company_data[
                                "default_account_expense"
                            ].id,
                            "currency_id": currency.id,
                            "amount_currency": -100.0,
                            "balance": -110.0,
                        }
                    ),
                ],
            }
        )
        line = move.line_ids.filtered(lambda line: line.balance > 0)
        action = line.action_split_lines()
        self.env[action["res_model"]].with_context(**action["context"]).create(
            {"quantity": 3}
        ).split()
        parts = move.line_ids.filtered(
            lambda line: line.account_id == self.revenue_account
        )
        self.assertEqual(len(parts), 3)
        self.assertAlmostEqual(sum(parts.mapped("balance")), 110.0)
        self.assertAlmostEqual(sum(parts.mapped("amount_currency")), 100.0)

    def test_exclude_bank_lines_follows_the_line_account(self):
        bank_journal = self.company_data["default_journal_bank"]
        move = self.env["account.move"].create(
            {
                "move_type": "entry",
                "date": "2019-01-01",
                "journal_id": bank_journal.id,
                "line_ids": [
                    Command.create(
                        {
                            "account_id": bank_journal.default_account_id.id,
                            "balance": 50.0,
                        }
                    ),
                    Command.create(
                        {"account_id": self.revenue_account.id, "balance": -50.0}
                    ),
                ],
            }
        )
        bank_line = move.line_ids.filtered(lambda line: line.balance > 0)
        self.assertFalse(bank_line.exclude_bank_lines)
        bank_line.account_id = self.company_data["default_account_assets"]
        self.assertTrue(bank_line.exclude_bank_lines)

    def test_transfer_keeps_a_remainder_below_the_foreign_rounding(self):
        currency = self.setup_other_currency("JPY", rounding=1.0)
        payable = self.create_line_for_reconciliation(
            -100.30,
            -10030.0,
            currency,
            "2016-01-01",
            account_1=self.payable_account,
            partner=self.partner_a,
        )
        receivables = self.env["account.move.line"]
        for partner, balance in ((self.partner_a, 100.0), (self.partner_b, 50.0)):
            receivables += self.create_line_for_reconciliation(
                balance, balance * 100, currency, "2016-01-01", partner=partner
            )
        wizard = (
            self.env["account.reconcile.wizard"]
            .with_context(
                active_model="account.move.line",
                active_ids=(payable + receivables).ids,
            )
            .new({"journal_id": self.misc_journal.id, "allow_partials": True})
        )
        transfer_move = wizard.create_transfer()
        self.assertEqual(transfer_move.state, "posted")
        self.assertRecordValues(
            transfer_move.line_ids.sorted("balance"),
            [
                {"partner_id": self.partner_a.id, "balance": -100.0},
                {"partner_id": self.partner_b.id, "balance": -0.30},
                {"partner_id": self.partner_a.id, "balance": 100.30},
            ],
        )

    def test_analytic_coverage_sql_uses_the_given_alias(self):
        self.env.user.group_ids += self.env.ref("analytic.group_analytic_accounting")
        move = self._misc_move(
            [
                {
                    "account_id": self.revenue_account.id,
                    "balance": 100.0,
                    "analytic_distribution": {str(self.analytic_account.id): 60},
                },
                {"account_id": self.receivable_account.id, "balance": -100.0},
            ]
        )
        line = move.line_ids.filtered(lambda line: line.balance > 0)
        lines = self.env["account.move.line"].with_context(
            selected_analytic_plan=self.analytic_plan.id
        )
        query = lines._search([("id", "=", line.id)])
        coverage = lines._field_to_sql(query.table, "analytic_coverage", query)
        self.assertEqual(self.env.execute_query(query.select(coverage)), [(0.6,)])

    def test_unreconcile_match_entries_acts_on_its_records(self):
        lines = self.env["account.move.line"]
        for balance in (100.0, -100.0):
            lines += self.create_line_for_reconciliation(
                balance, balance, self.company_data["currency"], "2016-01-01"
            )
        lines.reconcile()
        self.assertTrue(lines.full_reconcile_id)
        lines.with_context(active_ids=None).action_unreconcile_match_entries()
        self.assertFalse(lines.matched_debit_ids | lines.matched_credit_ids)


@tagged("post_install", "-at_install")
class TestMarinRevaluationWizardChoice(TestAccountReportsCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.company_data["company"]
        cls.config = cls.company.account_config_id
        cls.config.write(
            {
                "account_revaluation_journal_id": cls.company_data[
                    "default_journal_misc"
                ].id,
                "account_revaluation_expense_provision_account_id": cls.company_data[
                    "default_account_expense"
                ].id,
                "account_revaluation_income_provision_account_id": cls.company_data[
                    "default_account_revenue"
                ].id,
            }
        )
        currency = cls.setup_other_currency(
            "CHF", rates=[("2023-01-01", 1.0), ("2023-01-25", 2.0)]
        )
        cls.init_invoice(
            "out_invoice",
            invoice_date="2023-01-10",
            amounts=[1000.0],
            taxes=[],
            currency=currency,
            post=True,
        )
        cls.report = cls.env.ref("account.multicurrency_revaluation_report")
        cls.chosen_journal = cls.company_data["default_journal_misc"].copy(
            {"code": "CHJ"}
        )
        cls.chosen_expense = cls.company_data["default_account_expense"].copy()
        cls.chosen_income = cls.company_data["default_account_revenue"].copy()

    def _run_wizard(self, user):
        options = self._generate_options(self.report, "2023-01-01", "2023-01-31")
        env = self.env(
            user=user,
            context={
                **self.env.context,
                "multicurrency_revaluation_report_options": {
                    **options,
                    "unfold_all": False,
                },
            },
        )
        wizard = env["account.multicurrency.revaluation.wizard"].create(
            {
                "journal_id": self.chosen_journal.id,
                "expense_provision_account_id": self.chosen_expense.id,
                "income_provision_account_id": self.chosen_income.id,
            }
        )
        env.invalidate_all()
        action = wizard.create_entries()
        return self.env["account.move"].browse(action["res_id"])

    def test_an_accountant_books_on_the_chosen_journal_and_accounts(self):
        accountant = new_test_user(
            self.env,
            login="marin_reval_accountant",
            groups="account.group_account_user",
            company_id=self.company.id,
        )
        move = self._run_wizard(accountant)
        self.assertEqual(move.journal_id, self.chosen_journal)
        self.assertIn(self.chosen_expense, move.line_ids.account_id)
        self.assertEqual(
            self.config.account_revaluation_journal_id,
            self.company_data["default_journal_misc"],
        )

    def test_a_manager_choice_becomes_the_company_default(self):
        manager = new_test_user(
            self.env,
            login="marin_reval_mgr",
            groups="account.group_account_user,account.group_account_manager",
            company_id=self.company.id,
        )
        move = self._run_wizard(manager)
        self.assertEqual(move.journal_id, self.chosen_journal)
        self.assertEqual(
            self.config.account_revaluation_journal_id, self.chosen_journal
        )
