from odoo import Command
from odoo.tests import tagged

from odoo.addons.account.tests.common_report_engine import TestAccountReportsCommon


@tagged("post_install", "-at_install")
class TestMarinReportFiscalyearScopes(TestAccountReportsCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.company_data["company"]
        cls.company_data_march = cls.setup_other_company(
            name="company_fy_march_scopes", currency_id=cls.company_a.currency_id.id
        )
        cls.company_b = cls.company_data_march["company"]
        cls.company_b.account_config_id.write(
            {"fiscalyear_last_month": "3", "fiscalyear_last_day": 31}
        )
        for company_data, amounts in (
            (cls.company_data, (100.0, 200.0)),
            (cls.company_data_march, (1000.0, 2000.0)),
        ):
            for date, amount in zip(("2025-02-15", "2025-04-15"), amounts, strict=True):
                cls.env["account.move"].create(
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
                ).action_post()
        cls.report = cls.env.ref("account.balance_sheet")

    def _get_earnings(self, companies):
        report = self.report.with_context(allowed_company_ids=companies.ids)
        options = self._generate_options(report, "2025-05-01", "2025-05-31")
        self.assertEqual(
            {company["id"] for company in options["companies"]}, set(companies.ids)
        )
        lines = report._get_lines(options)
        return tuple(
            report._get_line_from_xml_id(lines, xml_id)["columns"][0]["no_format"]
            for xml_id in (
                "account.account_financial_report_current_years_earnings",
                "account.account_financial_report_previous_years_earnings",
            )
        )

    def test_balance_sheet_earnings_follow_each_company_fiscal_year(self):
        current_a, previous_a = self._get_earnings(self.company_a)
        current_b, previous_b = self._get_earnings(self.company_b)
        self.assertEqual((abs(current_a), abs(previous_a)), (300.0, 0.0))
        self.assertEqual((abs(current_b), abs(previous_b)), (2000.0, 1000.0))

        for companies in (
            self.company_a + self.company_b,
            self.company_b + self.company_a,
        ):
            with self.subTest(main_company=companies[0].name):
                self.assertEqual(
                    self._get_earnings(companies),
                    (current_a + current_b, previous_a + previous_b),
                )
