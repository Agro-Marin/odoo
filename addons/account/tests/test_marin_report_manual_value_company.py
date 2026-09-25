from odoo import Command
from odoo.tests import tagged

from odoo.addons.account.tests.common_report_engine import TestAccountReportsCommon


@tagged("post_install", "-at_install")
class TestMarinReportManualValueCompany(TestAccountReportsCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.company_data["company"]
        cls.company_b = cls.setup_other_company(
            name="company_fy_march_manual", currency_id=cls.company_a.currency_id.id
        )["company"]
        cls.company_b.account_config_id.write(
            {"fiscalyear_last_month": "3", "fiscalyear_last_day": 31}
        )
        cls.report = cls.env["report.formula"].create(
            {
                "name": "manual values per company",
                "filter_date_range": True,
                "column_ids": [
                    Command.create({"name": "balance", "expression_label": "balance"})
                ],
                "line_ids": [
                    Command.create(
                        {
                            "name": name,
                            "sequence": sequence,
                            "expression_ids": [
                                Command.create(
                                    {
                                        "label": "balance",
                                        "engine": "external",
                                        "formula": formula,
                                        "subformula": "editable",
                                        "date_scope": date_scope,
                                    }
                                )
                            ],
                        }
                    )
                    for sequence, (name, formula, date_scope) in enumerate(
                        (
                            ("from_fy", "sum", "from_fiscalyear"),
                            ("to_fy", "sum", "to_beginning_of_fiscalyear"),
                            ("most_recent", "most_recent", "from_beginning"),
                        )
                    )
                ],
            }
        )
        cls.expressions = {
            line.name: line.expression_ids for line in cls.report.line_ids
        }
        cls.env["report.formula.external.value"].create(
            [
                {
                    "name": f"{company.name} {date}",
                    "date": date,
                    "value": amount,
                    "company_id": company.id,
                    "target_report_expression_id": cls.expressions[name].id,
                }
                for company, amounts in (
                    (cls.company_a, (100.0, 200.0)),
                    (cls.company_b, (1000.0, 2000.0)),
                )
                for date, amount in zip(
                    ("2025-02-15", "2025-04-15"), amounts, strict=True
                )
                for name in ("from_fy", "to_fy", "most_recent")
            ]
        )

    def _values(self, company):
        report = self.report.with_context(allowed_company_ids=company.ids)
        options = self._generate_options(report, "2025-05-01", "2025-05-31")
        return {
            line["name"]: line["columns"][0]["no_format"]
            for line in report._get_lines(options)
        }

    def test_manual_value_lands_on_the_report_company_and_its_fiscal_year(self):
        options = self._generate_options(
            self.report.with_context(allowed_company_ids=self.company_b.ids),
            "2025-05-01",
            "2025-05-31",
        )
        self.assertEqual(
            [company["id"] for company in options["companies"]], self.company_b.ids
        )
        # the report shows company B while the user works in company A
        report = self.report.with_context(
            allowed_company_ids=(self.company_a + self.company_b).ids
        )
        column_group_options = report._get_column_group_options(
            options, next(iter(options["column_groups"]))
        )
        values_of_a = self._values(self.company_a)
        edits = {"from_fy": 5000.0, "to_fy": 1500.0, "most_recent": 300.0}
        for name, value in edits.items():
            report._action_modify_manual_external_value(
                column_group_options, str(value), self.expressions[name].id, 2
            )
        self.assertEqual(self._values(self.company_b), edits)
        self.assertEqual(self._values(self.company_a), values_of_a)
        created = self.env["report.formula.external.value"].search(
            [("name", "=", "Manual value")]
        )
        self.assertEqual(
            {
                (value.target_report_expression_id.report_line_id.name, str(value.date))
                for value in created
            },
            {
                ("from_fy", "2025-05-31"),
                ("to_fy", "2025-03-31"),
                ("most_recent", "2025-05-31"),
            },
        )
        self.assertEqual(created.company_id, self.company_b)


@tagged("post_install", "-at_install")
class TestMarinReportVariantSourceModel(TestAccountReportsCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        plan = cls.env["account.analytic.plan"].create({"name": "variant plan"})
        analytic_account = cls.env["account.analytic.account"].create(
            {"name": "variant account", "plan_id": plan.id}
        )
        cls.env["account.analytic.line"].create(
            [
                {
                    "name": f"variant line {amount}",
                    "account_id": analytic_account.id,
                    "date": "2020-01-01",
                    "amount": amount,
                }
                for amount in (100.0, 50.0)
            ]
        )
        cls.root = cls._create_analytic_report(
            source_model="account.analytic.line",
            source_date_field="date",
            source_measure_field="amount",
        )
        cls.variant = cls._create_analytic_report(root_report_id=cls.root.id)

    @classmethod
    def _create_analytic_report(cls, **values):
        return cls.env["report.formula"].create(
            {
                "name": "analytic lines",
                "filter_date_range": True,
                **values,
                "column_ids": [
                    Command.create({"name": "balance", "expression_label": "balance"})
                ],
                "line_ids": [
                    Command.create(
                        {
                            "name": "variant lines",
                            "expression_ids": [
                                Command.create(
                                    {
                                        "label": "balance",
                                        "engine": "domain",
                                        "formula": "[('name', 'like', 'variant line')]",
                                        "subformula": "sum",
                                        "date_scope": "strict_range",
                                    }
                                )
                            ],
                        }
                    )
                ],
            }
        )

    def test_a_variant_reads_the_source_model_of_its_root(self):
        self.assertFalse(self.variant.source_model)
        for report in (self.root, self.variant):
            with self.subTest(report="variant" if report.root_report_id else "root"):
                self.assertFalse(report._reads_ledger())
                options = self._generate_options(report, "2020-01-01", "2020-01-31")
                self.assertEqual(
                    report._get_lines(options)[0]["columns"][0]["no_format"], 150.0
                )

    def test_a_variant_of_a_ledger_report_reads_the_ledger(self):
        root = self.env.ref("account.balance_sheet")
        variant = root.copy(
            {"name": "balance sheet variant", "root_report_id": root.id}
        )
        self.assertTrue(root._reads_ledger())
        self.assertTrue(variant._reads_ledger())
