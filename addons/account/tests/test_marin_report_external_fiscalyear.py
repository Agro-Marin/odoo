from odoo import Command
from odoo.tests import tagged

from odoo.addons.account.tests.common_report_engine import TestAccountReportsCommon


@tagged("post_install", "-at_install")
class TestMarinReportExternalFiscalyear(TestAccountReportsCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.company_data["company"]
        cls.company_b = cls.setup_other_company(
            name="company_fy_march_external", currency_id=cls.company_a.currency_id.id
        )["company"]
        cls.company_b.account_config_id.write(
            {"fiscalyear_last_month": "3", "fiscalyear_last_day": 31}
        )
        cls.report = cls.env["report.formula"].create(
            {
                "name": "external fiscal years",
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
        values = []
        for company, amounts in (
            (cls.company_a, (100.0, 200.0)),
            (cls.company_b, (1000.0, 2000.0)),
        ):
            for date, amount in zip(("2025-02-15", "2025-04-15"), amounts, strict=True):
                values.extend(
                    {
                        "name": f"{company.name} {date}",
                        "date": date,
                        "value": amount,
                        "company_id": company.id,
                        "target_report_expression_id": cls.expressions[name].id,
                    }
                    for name in ("from_fy", "to_fy")
                )
        for company, date, amount in (
            (cls.company_a, "2025-02-15", 10.0),
            (cls.company_a, "2025-04-15", 20.0),
            (cls.company_b, "2025-02-15", 100.0),
        ):
            values.append(
                {
                    "name": f"{company.name} {date}",
                    "date": date,
                    "value": amount,
                    "company_id": company.id,
                    "target_report_expression_id": cls.expressions["most_recent"].id,
                }
            )
        cls.external_values = cls.env["report.formula.external.value"].create(values)

    def _options(self, companies):
        report = self.report.with_context(allowed_company_ids=companies.ids)
        options = self._generate_options(report, "2025-05-01", "2025-05-31")
        self.assertEqual(
            {company["id"] for company in options["companies"]}, set(companies.ids)
        )
        return report, options

    def _get_values(self, companies):
        report, options = self._options(companies)
        return {
            line["name"]: line["columns"][0]["no_format"]
            for line in report._get_lines(options)
        }

    def _expected_values(self, name, companies, dates):
        return self.external_values.filtered(
            lambda value: (
                value.target_report_expression_id == self.expressions[name]
                and value.company_id in companies
                and str(value.date) in dates
            )
        )

    def test_external_values_follow_each_company_fiscal_year(self):
        self.assertEqual(
            self._get_values(self.company_a),
            {"from_fy": 300.0, "to_fy": 0.0, "most_recent": 20.0},
        )
        self.assertEqual(
            self._get_values(self.company_b),
            {"from_fy": 2000.0, "to_fy": 1000.0, "most_recent": 100.0},
        )
        for companies in (
            self.company_a + self.company_b,
            self.company_b + self.company_a,
        ):
            with self.subTest(main_company=companies[0].name):
                self.assertEqual(
                    self._get_values(companies),
                    {"from_fy": 2300.0, "to_fy": 1000.0, "most_recent": 120.0},
                )

    def test_audit_and_carryover_lines_follow_each_company_fiscal_year(self):
        both = self.company_a + self.company_b
        expected = {
            "from_fy": self._expected_values("from_fy", both, {"2025-04-15"})
            | self._expected_values("from_fy", self.company_a, {"2025-02-15"}),
            "to_fy": self._expected_values("to_fy", self.company_b, {"2025-02-15"}),
            "most_recent": self._expected_values(
                "most_recent", self.company_a, {"2025-04-15"}
            )
            | self._expected_values("most_recent", self.company_b, {"2025-02-15"}),
        }
        ExternalValue = self.env["report.formula.external.value"]
        for companies in (both, self.company_b + self.company_a):
            report, options = self._options(companies)
            column_group_key = next(iter(options["column_groups"]))
            for name, expression in self.expressions.items():
                with self.subTest(main_company=companies[0].name, line=name):
                    audit = report.action_audit_cell(
                        options,
                        {
                            "report_line_id": expression.report_line_id.id,
                            "expression_label": "balance",
                            "column_group_key": column_group_key,
                        },
                    )
                    self.assertEqual(
                        ExternalValue.search(audit["domain"]), expected[name]
                    )
                    if expression.formula == "most_recent":
                        continue
                    carryover = expression.action_view_carryover_lines(
                        options, column_group_key=column_group_key
                    )
                    self.assertEqual(
                        ExternalValue.search(carryover["domain"]), expected[name]
                    )
