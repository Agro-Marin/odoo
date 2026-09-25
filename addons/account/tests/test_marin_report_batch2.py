from unittest.mock import patch

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.account.tests.common_report_engine import TestAccountReportsCommon


@tagged("post_install", "-at_install")
class TestMarinReportBatch2(TestAccountReportsCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.company_data["company"]
        cls.company_data_march = cls.setup_other_company(
            name="company_fy_march", currency_id=cls.company_a.currency_id.id
        )
        cls.company_b = cls.company_data_march["company"]
        cls.company_b.account_config_id.write(
            {"fiscalyear_last_month": "3", "fiscalyear_last_day": 31}
        )
        cls.env = cls.env(
            context=dict(
                cls.env.context,
                allowed_company_ids=[cls.company_a.id, cls.company_b.id],
            )
        )
        cls.revenue_a = cls.company_data["default_account_revenue"]
        cls.revenue_b = cls.company_data_march["default_account_revenue"]
        cls.pnl_lines = {}
        for company_data, amounts in (
            (cls.company_data, (100.0, 200.0)),
            (cls.company_data_march, (1000.0, 2000.0)),
        ):
            for date, amount in zip(("2025-02-15", "2025-04-15"), amounts, strict=True):
                move = cls.env["account.move"].create(
                    {
                        "move_type": "entry",
                        "date": date,
                        "journal_id": company_data["default_journal_misc"].id,
                        "line_ids": [
                            Command.create(
                                {
                                    "name": "receivable",
                                    "debit": amount,
                                    "account_id": company_data[
                                        "default_account_receivable"
                                    ].id,
                                }
                            ),
                            Command.create(
                                {
                                    "name": "revenue",
                                    "credit": amount,
                                    "account_id": company_data[
                                        "default_account_revenue"
                                    ].id,
                                }
                            ),
                        ],
                    }
                )
                move.action_post()
                cls.pnl_lines[company_data["company"], date] = move.line_ids.filtered(
                    lambda line, data=company_data: (
                        line.account_id == data["default_account_revenue"]
                    )
                )

    def _get_line(self, report, lines, model, res_id):
        return next(
            line
            for line in lines
            if report._get_model_info_from_id(line["id"]) == (model, res_id)
        )

    def _get_unallocated_line(self, report, lines, company):
        return next(
            (
                line
                for line in lines
                if report._get_markup(line["id"]) == "undistributed_profits_losses"
                and report._get_model_info_from_id(line["id"])
                == ("res.company", company.id)
            ),
            None,
        )

    def _get_balances(self, line):
        return [
            column["no_format"]
            for column in line["columns"]
            if column["expression_label"] == "balance"
        ]

    def test_general_ledger_cuts_each_company_pnl_at_its_own_fiscal_year(self):
        report = self.env.ref("account.general_ledger_report")
        options = self._generate_options(report, "2025-05-01", "2025-05-31")
        self.assertEqual(
            {company["id"] for company in options["companies"]},
            {self.company_a.id, self.company_b.id},
        )
        lines = report._get_lines(options)

        self.assertEqual(
            self._get_balances(
                self._get_line(report, lines, "account.account", self.revenue_a.id)
            ),
            [-300.0],
        )
        self.assertEqual(
            self._get_balances(
                self._get_line(report, lines, "account.account", self.revenue_b.id)
            ),
            [-2000.0],
        )
        self.assertIsNone(self._get_unallocated_line(report, lines, self.company_a))
        unallocated_b = self._get_unallocated_line(report, lines, self.company_b)
        self.assertIsNotNone(unallocated_b)
        self.assertEqual(self._get_balances(unallocated_b), [-1000.0])

        options["unfold_all"] = True
        unfolded = report._get_lines(options)
        revenue_b_line = self._get_line(
            report, unfolded, "account.account", self.revenue_b.id
        )
        initial_balance_b = next(
            line
            for line in unfolded
            if line.get("parent_id") == revenue_b_line["id"]
            and "balance_line" in line["id"]
        )
        self.assertEqual(self._get_balances(initial_balance_b), [-2000.0])

    def test_unallocated_items_open_the_lines_of_their_own_company_fiscal_year(self):
        report = self.env.ref("account.general_ledger_report")
        options = self._generate_options(report, "2025-05-01", "2025-05-31")
        lines = report._get_lines(options)
        unallocated_b = self._get_unallocated_line(report, lines, self.company_b)

        action = report.open_unallocated_items_journal_items(
            options, {"line_id": unallocated_b["id"]}
        )

        opened = self.env["account.move.line"].search(action["domain"])
        self.assertEqual(opened, self.pnl_lines[self.company_b, "2025-02-15"])
        self.assertEqual(sum(opened.mapped("balance")), -1000.0)

    def test_trial_balance_cuts_each_company_pnl_at_its_own_fiscal_year(self):
        report = self.env.ref("account.trial_balance_report")
        options = self._generate_options(report, "2025-05-01", "2025-05-31")
        initial_balance_group = options["columns"][0]["column_group_key"]
        lines = report._get_lines(options)

        self.assertEqual(
            self._get_balances(
                self._get_line(report, lines, "account.account", self.revenue_a.id)
            ),
            [-300.0, -300.0],
        )
        self.assertEqual(
            self._get_balances(
                self._get_line(report, lines, "account.account", self.revenue_b.id)
            ),
            [-2000.0, -2000.0],
        )
        self.assertIsNone(self._get_unallocated_line(report, lines, self.company_a))
        unallocated_b = self._get_unallocated_line(report, lines, self.company_b)
        self.assertIsNotNone(unallocated_b)
        self.assertEqual(self._get_balances(unallocated_b), [-1000.0, -1000.0])

        revenue_b_line = self._get_line(
            report, lines, "account.account", self.revenue_b.id
        )
        audit_domain = report.dispatch_report_action(
            options,
            "action_audit_cell",
            self._get_audit_params_from_report_line(
                options,
                report.line_ids[0],
                revenue_b_line,
                column_group_key=initial_balance_group,
            ),
        )["domain"]
        self.assertEqual(
            self.env["account.move.line"].search(audit_domain),
            self.pnl_lines[self.company_b, "2025-04-15"],
        )

        unallocated_audit_domain = report.dispatch_report_action(
            options,
            "action_audit_cell",
            self._get_audit_params_from_report_line(
                options,
                report.line_ids[0],
                unallocated_b,
                column_group_key=initial_balance_group,
            ),
        )["domain"]
        self.assertEqual(
            self.env["account.move.line"].search(unallocated_audit_domain),
            self.pnl_lines[self.company_b, "2025-02-15"],
        )

    def test_trial_balance_opens_a_block_where_any_company_fiscal_year_turns(self):
        report = self.env.ref("account.trial_balance_report")
        options = self._generate_options(
            report,
            "2025-04-01",
            "2025-04-30",
            default_options={
                "comparison": {
                    "filter": "previous_period",
                    "number_period": 1,
                    "period_order": "ascending",
                },
            },
        )
        self.assertEqual(
            [header["name"] for header in options["column_headers"][0]],
            [
                "Initial Balance",
                "Mar 2025",
                "End Balance",
                "Initial Balance",
                "Apr 2025",
                "End Balance",
            ],
        )
        lines = report._get_lines(options)
        self.assertEqual(
            self._get_balances(
                self._get_line(report, lines, "account.account", self.revenue_b.id)
            ),
            [-1000.0, -1000.0, 0.0, -2000.0],
        )
        self.assertEqual(
            self._get_balances(
                self._get_line(report, lines, "account.account", self.revenue_a.id)
            ),
            [-100.0, -100.0, -100.0, -300.0],
        )
        unallocated_b = self._get_unallocated_line(report, lines, self.company_b)
        self.assertEqual(
            self._get_balances(unallocated_b), [0.0, 0.0, -1000.0, -1000.0]
        )

    def test_fiscalyear_start_is_resolved_per_company(self):
        report = self.env.ref("account.general_ledger_report")
        options = self._generate_options(
            report,
            "2025-05-01",
            "2025-05-31",
        )
        starts = report._get_fiscalyear_start_by_company(options)
        self.assertEqual(
            starts,
            {
                self.company_a.id: fields.Date.to_date("2025-01-01"),
                self.company_b.id: fields.Date.to_date("2025-04-01"),
            },
        )


@tagged("post_install", "-at_install")
class TestMarinRevaluationWizardRuns(TestAccountReportsCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.report = cls.env.ref("account.multicurrency_revaluation_report")
        cls.currency = cls.setup_other_currency(
            "CHF", rates=[("2023-01-01", 1.0), ("2023-01-25", 2.0)]
        )
        cls.init_invoice(
            "out_invoice",
            invoice_date="2023-01-10",
            amounts=[1000.0],
            taxes=[],
            currency=cls.currency,
            post=True,
        )
        cls.wizard_values = {
            "journal_id": cls.company_data["default_journal_misc"].id,
            "expense_provision_account_id": cls.company_data[
                "default_account_expense"
            ].id,
            "income_provision_account_id": cls.company_data[
                "default_account_revenue"
            ].id,
        }

    def _count_report_runs(self):
        report_runs = []
        get_lines = type(self.report)._get_lines

        def counting_get_lines(report, options, *args, **kwargs):
            if report == self.report:
                report_runs.append(options.get("date", {}).get("date_to"))
            return get_lines(report, options, *args, **kwargs)

        return report_runs, patch.object(
            type(self.report), "_get_lines", counting_get_lines
        )

    def test_the_report_runs_once_from_the_report_button_to_the_posted_entry(self):
        options = self._generate_options(self.report, "2023-01-01", "2023-01-31")
        handler = self.env[self.report.custom_handler_model_name]
        report_runs, counting = self._count_report_runs()
        with counting:
            action = handler.action_multi_currency_revaluation_open_revaluation_wizard(
                options
            )
            Wizard = self.env["account.multicurrency.revaluation.wizard"].with_context(
                action["context"]
            )
            spec = {
                name: {}
                for name in ("date", "reversal_date", "preview_data", "company_id")
            }
            Wizard.onchange({}, [], spec)
            wizard = Wizard.create(self.wizard_values)
            self.assertTrue(wizard.preview_data)
            move_id = wizard.create_entries()["res_id"]
        self.assertEqual(len(report_runs), 1)
        self.assertEqual(
            self.env["account.move"].browse(move_id).line_ids.mapped("balance"),
            [-500.0, 500.0],
        )

    def test_a_wizard_created_without_the_button_runs_the_report_once(self):
        options = self._generate_options(self.report, "2023-01-01", "2023-01-31")
        report_runs, counting = self._count_report_runs()
        with counting:
            wizard = (
                self.env["account.multicurrency.revaluation.wizard"]
                .with_context(multicurrency_revaluation_report_options=options)
                .create(self.wizard_values)
            )
            wizard.create_entries()
        self.assertEqual(len(report_runs), 1)

    def test_the_wizard_refuses_when_nothing_needs_adjusting(self):
        options = self._generate_options(self.report, "2022-01-01", "2022-12-31")
        handler = self.env[self.report.custom_handler_model_name]
        action = handler.action_multi_currency_revaluation_open_revaluation_wizard(
            options
        )
        self.assertEqual(action["context"]["default_adjustment_vals"], [])

        Wizard = self.env[action["res_model"]].with_context(action["context"])
        report_runs, counting = self._count_report_runs()
        with counting, self.assertRaisesRegex(UserError, "No adjustment needed"):
            Wizard.create({})
        self.assertEqual(report_runs, [])
