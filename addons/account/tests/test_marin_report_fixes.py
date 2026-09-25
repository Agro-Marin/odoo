import datetime
from unittest.mock import patch

from freezegun import freeze_time

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tools import SQL

from odoo.addons.account.tests.common_report_engine import TestAccountReportsCommon


@tagged("post_install", "-at_install")
class TestMarinReportFixes(TestAccountReportsCommon):
    def _post_invoice(self, partner, amount, invoice_date, due_date=None, **kwargs):
        move = self.init_invoice(
            kwargs.pop("move_type", "out_invoice"),
            partner=partner,
            invoice_date=invoice_date,
            amounts=[amount],
            **kwargs,
        )
        if due_date:
            move.invoice_payment_term_id = False
            move.invoice_date_due = due_date
        move.action_post()
        return move

    def test_revaluation_account_lines_under_to_adjust_are_included(self):
        report = self.env.ref("account.multicurrency_revaluation_report")
        self._post_invoice(
            self.partner_a, 800.0, "2016-06-01", currency=self.other_currency
        )
        options = self._generate_options(report, "2017-01-01", "2017-12-31")
        options["unfold_all"] = True

        account_lines = [
            line
            for line in report._get_lines(options)
            if report._get_model_info_from_id(line["id"])[0] == "account.account"
        ]

        self.assertTrue(account_lines)
        self.assertTrue(all(line["is_included_line"] for line in account_lines))

    def test_aged_audit_follows_the_aging_basis(self):
        report = self.env.ref("account.aged_receivable_report")
        handler = self.env["account.aged.receivable.report.handler"]
        partner = self._create_partner(name="aged audit partner")
        invoice = self._post_invoice(
            partner, 100.0, "2025-01-01", due_date="2025-03-15"
        )
        receivable_line = invoice.line_ids.filtered(
            lambda line: line.account_id.account_type == "asset_receivable"
        )
        line_dict_id = self._get_basic_line_dict_id_from_report_line_ref(
            "account.aged_receivable_line"
        )

        def audited_periods(options):
            periods = []
            for label in [f"period{i}" for i in range(6)]:
                action = handler.action_audit_cell(
                    options,
                    {"calling_line_dict_id": line_dict_id, "expression_label": label},
                )
                if receivable_line & self.env["account.move.line"].search(
                    action["domain"]
                ):
                    periods.append(label)
            return periods

        options = self._generate_options(report, "2025-03-31", "2025-03-31")
        self.assertEqual(audited_periods(options), ["period1"])

        options = self._generate_options(
            report,
            "2025-03-31",
            "2025-03-31",
            default_options={"aging_based_on": "base_on_invoice_date"},
        )
        self.assertEqual(options["aging_based_on"], "base_on_invoice_date")
        self.assertEqual(audited_periods(options), ["period3"])

    @freeze_time("2025-10-08")
    def test_followup_load_more_emits_each_status_header_once(self):
        report = self.env.ref("account.followup_report")
        report.load_more_limit = 2
        for due_date in ("2025-01-01", "2025-02-01", "2025-03-01"):
            self._post_invoice(self.partner_a, 100.0, "2025-01-01", due_date=due_date)
        for due_date in ("2025-11-01", "2025-12-01", "2025-12-15"):
            self._post_invoice(self.partner_a, 100.0, "2025-01-01", due_date=due_date)
        translations = {"Overdue": "Vencido", "Due": "Por vencer"}
        real_translate = type(self.env)._

        def translate(env, source, *args, **kwargs):
            if source in translations:
                return translations[source]
            return real_translate(env, source, *args, **kwargs)

        options = self._generate_options(report, "2025-01-01", "2025-12-31")
        options["unfold_all"] = True
        options["unfolded_lines"] = []
        with patch.object(type(self.env), "_", translate):
            lines = report._get_lines(options)
            pending = [line for line in lines if line.get("offset")]
            while pending:
                load_more = pending.pop()
                page = report.get_expanded_lines(
                    options,
                    load_more["parent_id"],
                    load_more["groupby"],
                    load_more["expand_function"],
                    load_more["progress"],
                    load_more["offset"],
                    None,
                )
                lines += page
                pending += [line for line in page if line.get("offset")]

        partner_lines = [
            line
            for line in lines
            if line.get("parent_id")
            and report._get_res_id_from_line_id(line["id"], "res.partner")
            == self.partner_a.id
        ]
        headers = [line["name"] for line in partner_lines if line.get("unfolded")]
        self.assertEqual(headers, ["Vencido", "Por vencer"])
        self.assertEqual(
            len(
                [
                    line
                    for line in lines
                    if line.get("caret_options") == "account.move.line"
                ]
            ),
            6,
        )

    def test_followup_due_today_uses_the_user_timezone(self):
        handler = self.env["account.followup.report.handler"]
        aml = {"date_maturity": datetime.date(2025, 10, 8)}
        with freeze_time("2025-10-09 03:00:00"):
            handler = handler.with_context(tz="America/Mexico_City")
            self.assertEqual(handler._filter_overdue_amls_from_results([aml]), [])
            self.assertEqual(handler._filter_due_amls_from_results([aml]), [aml])

    def test_customer_statement_unknown_partner_amount_matches_balance(self):
        report = self.env.ref("account.customer_statement_report")
        invoice = self._post_invoice(self.partner_a, 1000.0, "2017-01-01")
        receivable = invoice.line_ids.filtered(
            lambda line: line.account_id.account_type == "asset_receivable"
        )
        misc_move = self.env["account.move"].create(
            {
                "date": "2017-03-31",
                "line_ids": [
                    Command.create(
                        {
                            "debit": 400.0,
                            "account_id": self.company_data[
                                "default_account_revenue"
                            ].id,
                        }
                    ),
                    Command.create(
                        {
                            "credit": 400.0,
                            "account_id": receivable.account_id.id,
                        }
                    ),
                ],
            }
        )
        misc_move.action_post()
        (
            receivable
            + misc_move.line_ids.filtered(
                lambda line: line.account_id == receivable.account_id
            )
        ).reconcile()

        options = self._generate_options(report, "2018-01-01", "2018-12-31")
        unknown_partner_line = next(
            line
            for line in report._get_lines(options)
            if report._get_model_info_from_id(line["id"]) == ("res.partner", None)
        )
        values = {
            column["expression_label"]: column["no_format"]
            for column in unknown_partner_line["columns"]
        }
        self.assertAlmostEqual(values["amount"], values["balance"])

    def test_budget_shadow_rows_carry_the_budget_company(self):
        report = self.env["report.formula"].create(
            {
                "name": "Budget shadow",
                "filter_date_range": True,
                "filter_budgets": True,
                "column_ids": [
                    Command.create({"name": "Balance", "expression_label": "balance"})
                ],
                "line_ids": [
                    Command.create(
                        {
                            "name": "income",
                            "expression_ids": [
                                Command.create(
                                    {
                                        "label": "balance",
                                        "formula": "[('account_id.account_type', '=', 'income')]",
                                        "subformula": "sum",
                                        "engine": "domain",
                                    }
                                )
                            ],
                        }
                    )
                ],
            }
        )
        other_company = self.company_data_2["company"]
        budget = self.env["account.report.budget"].create(
            {
                "name": "Other company budget",
                "company_id": other_company.id,
                "item_ids": [
                    Command.create(
                        {
                            "amount": 100.0,
                            "account_id": self.company_data_2[
                                "default_account_revenue"
                            ].id,
                            "date": "2024-01-01",
                        }
                    )
                ],
            }
        )
        options = self._generate_options(
            report,
            "2024-01-01",
            "2024-12-31",
            default_options={
                "budgets": [{"id": budget.id, "selected": True}],
                "show_all_accounts": True,
            },
        )
        options["budgets"] = [{"id": budget.id, "selected": True}]
        shadow_query = report._create_aml_shadowing_query_for_budget(options)
        self.env.flush_all()
        self.env.cr.execute("SAVEPOINT marin_read_only_probe")
        try:
            self.env.cr.execute("SET TRANSACTION READ ONLY")
            rows = self.env.execute_query(
                SQL("SELECT DISTINCT shadow.company_id FROM %s AS shadow", shadow_query)
            )
        finally:
            self.env.cr.execute("ROLLBACK TO SAVEPOINT marin_read_only_probe")
        self.assertEqual({company_id for (company_id,) in rows}, {other_company.id})

    def test_budget_sign_honours_excluded_prefixes(self):
        account = self.company_data["default_account_revenue"]
        other = self.copy_account(account, default={"code": f"{account.code[:3]}999"})
        report = self.env["report.formula"].create(
            {
                "name": "Budget sign",
                "filter_date_range": True,
                "filter_budgets": True,
                "column_ids": [
                    Command.create({"name": "Balance", "expression_label": "balance"})
                ],
                "line_ids": [
                    Command.create(
                        {
                            "name": "codes",
                            "groupby": "account_id",
                            "expression_ids": [
                                Command.create(
                                    {
                                        "label": "balance",
                                        "formula": f"-{account.code[:3]}\\({account.code})+{account.code}",
                                        "engine": "account_codes",
                                    }
                                )
                            ],
                        }
                    )
                ],
            }
        )
        budget = self.env["account.report.budget"].create({"name": "Signs"})
        column_group_options = {
            "compute_budget": budget.id,
            "date": {"date_from": "2024-01-01", "date_to": "2024-01-31"},
        }
        for target_account in (account, other):
            report._action_modify_manual_budget_value(
                report._get_generic_line_id("account.account", target_account.id),
                column_group_options,
                "100",
                report.line_ids.expression_ids.id,
                2,
            )
        self.assertRecordValues(
            budget.item_ids.sorted(lambda item: item.account_id != account),
            [
                {"account_id": account.id, "amount": 100.0},
                {"account_id": other.id, "amount": -100.0},
            ],
        )

    def test_budget_item_period_without_a_month_start_is_refused(self):
        budget = self.env["account.report.budget"].create({"name": "Mid month"})
        with self.assertRaises(UserError):
            budget._create_or_update_budget_items(
                value_to_set=100.0,
                account_id=self.company_data["default_account_revenue"].id,
                rounding=2,
                date_from="2024-03-15",
                date_to="2024-03-31",
            )

    def test_tax_report_archived_tags_action_stops_at_the_period_end(self):
        handler = self.env["account.generic.tax.report.handler"]
        tag = self.env["account.account.tag"].create(
            {
                "name": "archived tag",
                "applicability": "taxes",
                "country_id": self.env.company.country_id.id,
                "active": False,
            }
        )
        moves = self.env["account.move"].create(
            [
                {
                    "date": move_date,
                    "line_ids": [
                        Command.create(
                            {
                                "debit": 10.0,
                                "account_id": self.company_data[
                                    "default_account_revenue"
                                ].id,
                                "tax_tag_ids": [Command.set(tag.ids)],
                            }
                        ),
                        Command.create(
                            {
                                "credit": 10.0,
                                "account_id": self.company_data[
                                    "default_account_assets"
                                ].id,
                            }
                        ),
                    ],
                }
                for move_date in ("2024-01-15", "2024-02-15")
            ]
        )
        moves.action_post()
        options = self._generate_options(
            self.env.ref("account.generic_tax_report"), "2024-01-01", "2024-01-31"
        )
        found = (
            self.env["account.move.line"]
            .with_context(active_test=False)
            .search(handler._get_domain_amls_with_archived_tags(options))
        )
        self.assertEqual(found.move_id, moves[0])

    def test_deleting_an_annotated_message_deletes_the_annotation(self):
        message = self.env["mail.message"].create(
            {"body": "annotated", "model": "res.partner", "res_id": self.partner_a.id}
        )
        annotation = self.env["account.report.annotation"].create(
            {"message_id": message.id, "date": "2024-01-01"}
        )
        message.unlink()
        self.assertFalse(annotation.exists())

    def test_annotation_fiscal_year_start_follows_the_company(self):
        report = self.env.ref("account.balance_sheet")
        self.env.company.account_config_id.write(
            {"fiscalyear_last_day": 31, "fiscalyear_last_month": "3"}
        )
        options = self._generate_options(report, "2026-04-01", "2027-03-31")
        options["date"]["period_type"] = "fiscalyear"
        options["date"]["filter"] = "this_year"
        options["date"]["mode"] = "range"
        self.assertEqual(
            report._get_annotations_domain_date_from(options),
            datetime.datetime(2026, 4, 1),
        )

    def test_return_names_refresh_when_account_terms_load(self):
        self.env["res.lang"]._activate_lang("fr_FR")
        return_model = type(self.env["account.return"])
        with patch.object(return_model, "_update_translated_name") as update:
            self.env["ir.module.module"]._load_module_terms(["account"], ["fr_FR"])
        self.assertTrue(update.called)

    def test_setting_main_vat_partner_keeps_its_own_contacts(self):
        main = self.env["res.partner"].create(
            {"name": "Main", "is_company": True, "vat": "BE0477472701"}
        )
        contact = self.env["res.partner"].create(
            {"name": "Contact", "parent_id": main.id, "type": "contact"}
        )
        duplicate = self.env["res.partner"].create(
            {"name": "Duplicate", "is_company": True, "vat": "BE0477472701"}
        )
        main.set_commercial_partner_main()
        self.assertRecordValues(
            contact + duplicate,
            [
                {"parent_id": main.id, "type": "contact"},
                {"parent_id": main.id, "type": "invoice"},
            ],
        )

    def test_generic_tax_reports_render_with_a_branch_selected(self):
        company = self.env.company
        branch = self.env["res.company"].create(
            {"name": "Tax report branch", "parent_id": company.id}
        )
        self.env.user.company_ids |= branch
        tax = self.tax_sale_a
        self._post_invoice(self.partner_a, 100.0, "2017-03-01", taxes=tax)
        for xmlid in (
            "account.generic_tax_report",
            "account.generic_tax_report_account_tax",
            "account.generic_tax_report_tax_account",
        ):
            report = self.env.ref(xmlid).with_context(
                allowed_company_ids=(company | branch).ids
            )
            options = self._generate_options(report, "2017-01-01", "2017-12-31")
            options["unfold_all"] = True
            self.assertEqual(len(options["companies"]), 2, xmlid)

            names = [line["name"] for line in report._get_lines(options)]

            self.assertIn(f"{tax.name} ({tax.amount}%)", names, xmlid)

    def test_setting_main_vat_partner_absorbs_a_subsidiary_duplicate(self):
        holding = self.env["res.partner"].create(
            {"name": "Holding", "is_company": True}
        )
        main = self.env["res.partner"].create(
            {"name": "Main", "is_company": True, "vat": "BE0477472701"}
        )
        subsidiary = self.env["res.partner"].create(
            {
                "name": "Subsidiary",
                "is_company": True,
                "vat": "BE0477472701",
                "parent_id": holding.id,
            }
        )
        self.assertEqual(subsidiary.commercial_partner_id, subsidiary)

        main.set_commercial_partner_main()

        self.assertEqual(subsidiary.parent_id, main)
        self.assertEqual(subsidiary.commercial_partner_id, main)

    def test_setting_main_vat_partner_leaves_its_ancestors_alone(self):
        parent = self.env["res.partner"].create(
            {"name": "Parent", "is_company": True, "vat": "BE0477472701"}
        )
        main = self.env["res.partner"].create(
            {
                "name": "Main",
                "is_company": True,
                "vat": "BE0477472701",
                "parent_id": parent.id,
            }
        )

        main.set_commercial_partner_main()

        self.assertFalse(parent.parent_id)
        self.assertEqual(main.parent_id, parent)

    def test_partner_ledger_pages_split_partials_of_one_line_deterministically(self):
        handler = self.env["account.partner.ledger.report.handler"]
        report = self.env.ref("account.partner_ledger_report")
        invoices = self._post_invoice(
            self.partner_a, 100.0, "2017-01-01"
        ) + self._post_invoice(self.partner_a, 100.0, "2017-01-01")
        receivable_lines = invoices.line_ids.filtered(
            lambda line: line.account_id.account_type == "asset_receivable"
        )
        misc_move = self.env["account.move"].create(
            {
                "date": "2017-02-01",
                "line_ids": [
                    Command.create(
                        {
                            "debit": 200.0,
                            "account_id": self.company_data[
                                "default_account_revenue"
                            ].id,
                        }
                    ),
                    Command.create(
                        {
                            "credit": 200.0,
                            "account_id": receivable_lines.account_id.id,
                        }
                    ),
                ],
            }
        )
        misc_move.action_post()
        (
            receivable_lines
            + misc_move.line_ids.filtered(
                lambda line: line.account_id == receivable_lines.account_id
            )
        ).reconcile()
        options = self._generate_options(report, "2017-01-01", "2017-12-31")
        report._init_currency_table(options)

        def rows(offset=0, limit=None):
            values = handler._prepare_aml_values(
                options, [self.partner_a.id], offset=offset, limit=limit
            )[self.partner_a.id]
            return [(row["id"], row["partial_id"]) for row in values]

        unpaged = rows()
        paged = [row for offset in range(len(unpaged)) for row in rows(offset, 1)]

        self.assertEqual(len({partial for _aml, partial in unpaged if partial}), 2)
        self.assertEqual(paged, unpaged)

    def test_reparenting_several_companies_with_opening_dates(self):
        companies = self.env["res.company"].create(
            [
                {"name": "Branch A", "parent_id": self.env.company.id},
                {"name": "Branch B", "parent_id": self.env.company.id},
            ]
        )
        companies.account_config_id.write({"account_opening_date": "2024-01-01"})
        with patch.object(
            type(self.env["account.return.type"]), "_sync_all_returns"
        ) as sync:
            companies.write({"parent_id": self.env.company.id})
        sync.assert_called_once()
        self.assertEqual(sync.call_args.args[0], self.env.company.root_id)

    def test_general_ledger_initial_balance_hides_mixed_currencies(self):
        report = self.env.ref("account.general_ledger_report")
        self.env.user.group_ids |= self.env.ref("base.group_multi_currency")
        second_currency = self.setup_other_currency("CHF")
        account = self.env["account.account"].create(
            {"name": "mixed", "code": "MIX01", "account_type": "asset_current"}
        )
        counterpart = self.company_data["default_account_revenue"]
        move = self.env["account.move"].create(
            {
                "date": "2016-06-01",
                "line_ids": [
                    Command.create(
                        {
                            "debit": 100.0,
                            "amount_currency": 300.0,
                            "currency_id": self.other_currency.id,
                            "account_id": account.id,
                        }
                    ),
                    Command.create(
                        {
                            "debit": 50.0,
                            "amount_currency": 150.0,
                            "currency_id": second_currency.id,
                            "account_id": account.id,
                        }
                    ),
                    Command.create({"credit": 150.0, "account_id": counterpart.id}),
                ],
            }
        )
        move.action_post()
        options = self._generate_options(report, "2017-01-01", "2017-12-31")
        options["unfolded_lines"] = [
            report._get_generic_line_id(
                "account.account",
                account.id,
                markup={"groupby": "account_id"},
                parent_line_id=report._get_generic_line_id(
                    "report.formula.line",
                    self.env.ref("account.general_ledger_custom_engine_line").id,
                ),
            )
        ]
        initial_balance = next(
            line
            for line in report._get_lines(options)
            if line["name"] == "Initial Balance"
        )
        amount_currency = next(
            column
            for column in initial_balance["columns"]
            if column["expression_label"] == "amount_currency"
        )
        self.assertFalse(amount_currency["no_format"])

    def test_deferred_expense_report_includes_other_expense_accounts(self):
        report = self.env.ref("account.deferred_expense_report")
        account = self.env["account.account"].create(
            {"name": "Other expense", "code": "OEXP1", "account_type": "expense_other"}
        )
        bill = self.env["account.move"].create(
            {
                "move_type": "in_invoice",
                "partner_id": self.partner_a.id,
                "invoice_date": "2023-01-01",
                "date": "2023-01-01",
                "invoice_line_ids": [
                    Command.create(
                        {
                            "name": "deferred",
                            "account_id": account.id,
                            "price_unit": 1200.0,
                            "deferred_start_date": "2023-01-01",
                            "deferred_end_date": "2023-12-31",
                        }
                    )
                ],
            }
        )
        bill.action_post()
        self.env.cr.cache.pop("report_deferred_lines", None)
        options = self._generate_options(report, "2023-01-01", "2023-01-31")
        handler = self.env["account.deferred.expense.report.handler"]
        lines = handler._get_lines(report, options)
        self.assertIn(account.id, {line["account_id"] for line in lines})

    def test_deferred_generation_ignores_draft_lines_seen_by_the_report(self):
        report = self.env.ref("account.deferred_expense_report")
        company_config = self.env.company.account_config_id
        company_config.write(
            {
                "deferred_expense_journal_id": self.company_data[
                    "default_journal_misc"
                ].id,
                "deferred_expense_account_id": self.company_data[
                    "default_account_deferred_expense"
                ].id,
            }
        )
        self.env["account.move"].create(
            {
                "move_type": "in_invoice",
                "partner_id": self.partner_a.id,
                "invoice_date": "2023-01-01",
                "date": "2023-01-01",
                "invoice_line_ids": [
                    Command.create(
                        {
                            "name": "draft deferred",
                            "account_id": self.company_data[
                                "default_account_expense"
                            ].id,
                            "price_unit": 1200.0,
                            "deferred_start_date": "2023-01-01",
                            "deferred_end_date": "2023-12-31",
                        }
                    )
                ],
            }
        )
        self.env.cr.cache.pop("report_deferred_lines", None)
        handler = self.env["account.deferred.expense.report.handler"]
        options = self._generate_options(report, "2023-01-01", "2023-01-31")
        options["all_entries"] = True
        self.assertTrue(handler._get_lines(report, options))
        moves_lines_to_generate = handler._get_moves_to_defer(options)[0]
        self.assertFalse(moves_lines_to_generate)
        self.assertTrue(options["all_entries"])
