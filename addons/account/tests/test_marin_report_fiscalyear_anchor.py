import datetime
import json

from freezegun import freeze_time

from odoo import Command, fields
from odoo.tests import tagged

from odoo.addons.account.tests.common_report_engine import TestAccountReportsCommon

ANCHOR_WARNING = "account.common_warning_fiscalyear_anchor"


@tagged("post_install", "-at_install")
class TestMarinReportFiscalyearAnchor(TestAccountReportsCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.company_data["company"]
        cls.company_b = cls.setup_other_company(
            name="company_fy_march_anchor", currency_id=cls.company_a.currency_id.id
        )["company"]
        cls.company_b.account_config_id.write(
            {"fiscalyear_last_month": "3", "fiscalyear_last_day": 31}
        )
        cls.pnl = cls.env.ref("account.profit_and_loss")
        cls.balance_sheet = cls.env.ref("account.balance_sheet")

    def _preset_options(self, report, companies, date_filter, comparison=None):
        previous_options = {"date": {"filter": date_filter, "mode": "range"}}
        if comparison:
            previous_options["comparison"] = comparison
        return report.with_context(allowed_company_ids=companies.ids).get_options(
            previous_options
        )

    def _anchor_warning(self, report, companies, options):
        return (
            report.with_context(allowed_company_ids=companies.ids)
            .get_report_information(options)["warnings"]
            .get(ANCHOR_WARNING)
        )

    @freeze_time("2025-06-15")
    def test_fiscal_year_preset_is_anchored_on_the_main_company(self):
        for companies, expected_range in (
            (self.company_a + self.company_b, ("2025-01-01", "2025-12-31")),
            (self.company_b + self.company_a, ("2025-04-01", "2026-03-31")),
        ):
            with self.subTest(main_company=companies[0].name):
                options = self._preset_options(self.pnl, companies, "this_year")
                self.assertEqual(
                    (options["date"]["date_from"], options["date"]["date_to"]),
                    expected_range,
                )
                self.assertEqual(options["date"]["period_type"], "fiscalyear")

    @freeze_time("2025-06-15")
    def test_fiscal_year_preset_warns_about_companies_off_the_anchor(self):
        for companies, date_filter in (
            (self.company_a + self.company_b, "this_year"),
            (self.company_a + self.company_b, "today"),
            (self.company_b + self.company_a, "this_year"),
        ):
            with self.subTest(main_company=companies[0].name, date_filter=date_filter):
                options = self._preset_options(self.pnl, companies, date_filter)
                warning = self._anchor_warning(self.pnl, companies, options)
                self.assertTrue(warning)
                self.assertEqual(warning["main_company"], companies[0].display_name)
                self.assertEqual(warning["companies"], companies[1].display_name)

    @freeze_time("2025-06-15")
    def test_fiscal_year_comparison_warns_about_companies_off_the_anchor(self):
        companies = self.company_a + self.company_b
        options = self._preset_options(
            self.pnl,
            companies,
            "this_month",
            comparison={
                "filter": "custom",
                "date_from": "2024-01-01",
                "date_to": "2024-12-31",
            },
        )
        self.assertEqual(
            options["comparison"]["periods"][0]["period_type"], "fiscalyear"
        )
        self.assertTrue(self._anchor_warning(self.pnl, companies, options))

    @freeze_time("2025-06-15")
    def test_no_anchor_warning_when_the_period_does_not_follow_a_fiscal_year(self):
        for companies, report, date_filter in (
            (self.company_a + self.company_b, self.pnl, "this_month"),
            (self.company_a + self.company_b, self.pnl, "this_quarter"),
            (self.company_a + self.company_b, self.balance_sheet, "today"),
            (self.company_a, self.pnl, "this_year"),
            (self.company_b, self.pnl, "this_year"),
        ):
            with self.subTest(
                companies=companies.mapped("name"),
                report=report.name,
                date_filter=date_filter,
            ):
                options = self._preset_options(report, companies, date_filter)
                self.assertFalse(self._anchor_warning(report, companies, options))

    def test_annotation_window_opens_at_the_earliest_selected_fiscal_year(self):
        for companies in (
            self.company_a + self.company_b,
            self.company_b + self.company_a,
        ):
            with self.subTest(main_company=companies[0].name):
                report = self.balance_sheet.with_context(
                    allowed_company_ids=companies.ids
                )
                options = self._generate_options(report, False, "2025-05-31")
                self.assertEqual(options["date"]["mode"], "single")
                self.assertEqual(
                    report._get_annotations_domain_date_from(options),
                    datetime.datetime(2025, 1, 1),
                )


@tagged("post_install", "-at_install")
class TestMarinReturnCompanyScope(TestAccountReportsCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.company_data["company"]
        cls.company_b = cls.setup_other_company(
            name="company_fy_march_return", currency_id=cls.company_a.currency_id.id
        )["company"]
        cls.company_b.account_config_id.write(
            {"fiscalyear_last_month": "3", "fiscalyear_last_day": 31}
        )
        cls.tax_report = cls.env["report.formula"].create(
            {
                "root_report_id": cls.env.ref("account.generic_tax_report").id,
                "name": "Return company scope tax report",
            }
        )
        cls.return_type = cls.env["account.return.type"].create(
            {
                "name": "Return company scope VAT",
                "report_id": cls.tax_report.id,
                "default_deadline_start_date": "2024-01-01",
            }
        )
        cls.return_type.with_company(cls.company_a).deadline_periodicity = "monthly"
        cls.return_type.with_company(cls.company_b).deadline_periodicity = "trimester"
        cls.return_b = cls.return_type.with_context(
            forced_date_from=fields.Date.from_string("2025-04-01"),
            forced_date_to=fields.Date.from_string("2025-06-30"),
        )._try_create_returns_for_fiscal_year(cls.company_b, False)

    def test_closing_options_of_a_return_follow_its_company(self):
        self.assertEqual(len(self.return_b), 1)
        self.assertEqual(self.return_b.company_id, self.company_b)
        options = self.return_b.with_context(
            allowed_company_ids=(self.company_a + self.company_b).ids
        )._get_closing_report_options()
        self.assertEqual(
            [company["id"] for company in options["companies"]], self.company_b.ids
        )
        self.assertEqual(
            (options["date"]["date_from"], options["date"]["date_to"]),
            ("2025-04-01", "2025-06-30"),
        )
        self.assertEqual(options["return_periodicity"]["months_per_period"], 3)
        self.assertEqual(
            (
                options["return_periodicity"]["fy_start_day"],
                options["return_periodicity"]["fy_start_month"],
            ),
            (1, 4),
        )

    def test_report_action_of_a_return_is_scoped_to_its_companies(self):
        action = self.return_b.with_context(
            allowed_company_ids=(self.company_a + self.company_b).ids
        ).action_view_report()
        self.assertEqual(action["context"]["allowed_company_ids"], self.company_b.ids)
        options = self.tax_report.with_context(**action["context"]).get_options(
            action["params"]["options"]
        )
        self.assertEqual(
            [company["id"] for company in options["companies"]], self.company_b.ids
        )
        self.assertEqual(options["return_periodicity"]["months_per_period"], 3)

    def _create_return(self, return_type, company, date_from, date_to):
        return return_type.with_context(
            forced_date_from=fields.Date.from_string(date_from),
            forced_date_to=fields.Date.from_string(date_to),
        )._try_create_returns_for_fiscal_year(company, False)

    def test_working_files_of_an_audit_cover_its_companies(self):
        audit_b = self._create_return(
            self.env.ref("account.default_audit_return_type"),
            self.company_b,
            "2024-04-01",
            "2025-03-31",
        )
        action = audit_b.with_context(
            allowed_company_ids=(self.company_a + self.company_b).ids
        ).action_export_working_files()
        options = json.loads(action["data"]["options"])
        self.assertEqual(
            [company["id"] for company in options["companies"]], self.company_b.ids
        )

    def test_annual_closing_checks_read_the_return_companies(self):
        receivable = self.company_data["default_account_receivable"]
        self.env["account.move"].create(
            {
                "move_type": "entry",
                "date": "2024-06-15",
                "journal_id": self.company_data["default_journal_misc"].id,
                "line_ids": [
                    Command.create(
                        {
                            "name": "no partner",
                            "debit": 100.0,
                            "account_id": receivable.id,
                        }
                    ),
                    Command.create(
                        {
                            "name": "revenue",
                            "credit": 100.0,
                            "account_id": self.company_data[
                                "default_account_revenue"
                            ].id,
                        }
                    ),
                ],
            }
        ).action_post()
        annual_type = self.env.ref("account.annual_corporate_tax_return_type")
        both_companies = (self.company_a + self.company_b).ids
        for company, date_from, date_to, expected in (
            (self.company_a, "2024-01-01", "2024-12-31", "anomaly"),
            (self.company_b, "2024-04-01", "2025-03-31", "reviewed"),
        ):
            with self.subTest(company=company.name):
                annual_return = self._create_return(
                    annual_type, company, date_from, date_to
                )
                checks = annual_return.with_context(
                    allowed_company_ids=both_companies
                )._check_suite_annual_closing(set())
                self.assertEqual(
                    next(
                        check["result"]
                        for check in checks
                        if check["code"] == "check_unkown_partner_receivables"
                    ),
                    expected,
                )
