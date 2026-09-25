from unittest.mock import patch

from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon

FEBRUARY_30 = (
    "Incorrect fiscal year date: day is out of range for month. Month: 2; Day: 30"
)


@tagged("post_install", "-at_install")
class TestMarinMergeBatch2(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_data_2 = cls.setup_other_company(name="merge_batch2_company_b")

    def _merge_wizard(self, accounts):
        return (
            self.env["account.merge.wizard"]
            .with_context(
                allowed_company_ids=(
                    self.company_data["company"] + self.company_data_2["company"]
                ).ids,
                active_model="account.account",
                active_ids=accounts.ids,
            )
            .create({})
        )

    def test_an_account_merge_ignores_the_contact_merge_exclusions(self):
        account_a = self.company_data["default_account_revenue"]
        account_b = self.company_data_2["default_account_revenue"]
        move = self.env["account.move"].create(
            {
                "journal_id": self.company_data_2["default_journal_misc"].id,
                "date": "2024-07-20",
                "line_ids": [
                    Command.create({"account_id": account_b.id, "balance": 10.0}),
                    Command.create(
                        {
                            "account_id": self.company_data_2[
                                "default_account_receivable"
                            ].id,
                            "balance": -10.0,
                        }
                    ),
                ],
            }
        )
        PartnerMerge = type(self.env["base.partner.merge.automatic.wizard"])
        contact_exclusions = PartnerMerge._get_merge_tables_excluded

        def exclude_journal_items(wizard, model):
            return contact_exclusions(wizard, model) | {"account_move_line"}

        wizard = self._merge_wizard(account_a + account_b)
        with patch.object(
            PartnerMerge, "_get_merge_tables_excluded", exclude_journal_items
        ):
            wizard.action_merge()

        self.assertFalse(account_b.exists())
        self.assertEqual(
            move.line_ids[0].account_id,
            account_a,
            "a table only the contact merge skips must still be repointed",
        )

    def test_the_setup_wizard_reports_the_configuration_error(self):
        with self.assertRaisesRegex(ValidationError, FEBRUARY_30):
            self.env["account.financial.year.op"].create(
                {
                    "company_id": self.env.company.id,
                    "opening_date": "2026-01-01",
                    "fiscalyear_last_day": 30,
                    "fiscalyear_last_month": "2",
                }
            )
        wizard = self.env["account.financial.year.op"].create(
            {"company_id": self.env.company.id, "opening_date": "2026-01-01"}
        )
        with self.assertRaisesRegex(ValidationError, FEBRUARY_30):
            wizard.write({"fiscalyear_last_day": 30, "fiscalyear_last_month": "2"})

    def test_the_settings_report_the_configuration_error(self):
        with self.assertRaisesRegex(ValidationError, FEBRUARY_30):
            self.env["res.config.settings"].create(
                {"fiscalyear_last_day": 30, "fiscalyear_last_month": "2"}
            )

    def test_the_configuration_checks_the_fiscal_year_end(self):
        config = self.env.company.account_config_id
        config.write({"fiscalyear_last_day": 29, "fiscalyear_last_month": "2"})
        self.assertEqual(config.fiscalyear_last_day, 29)
        for day, month in ((30, "2"), (31, "4"), (0, "1"), (-1, "12")):
            with (
                self.subTest(day=day, month=month),
                self.assertRaisesRegex(
                    ValidationError,
                    f"Month: {month}; Day: {day}$",
                ),
            ):
                config.write(
                    {"fiscalyear_last_day": day, "fiscalyear_last_month": month}
                )

    def _chart_load(self, xmlid, code):
        return (
            self.env["account.chart.template"]
            .with_context(install_module="l10n_be")
            ._load_data(
                {
                    "account.account": {
                        xmlid: {
                            "name": xmlid,
                            "code": code,
                            "account_type": "income",
                        }
                    }
                }
            )["account.account"]
        )

    def test_a_chart_load_creates_its_company_records_without_warning(self):
        with self.assertNoLogs("odoo.models", "WARNING"):
            account = self._chart_load("merge_batch2_silent", "990010")
        self.assertEqual(
            account,
            self.env.ref(f"account.{self.env.company.id}_merge_batch2_silent"),
        )

    def test_the_outstanding_accounts_are_created_without_warning(self):
        company = self.env["res.company"].create({"name": "merge_batch2_company_c"})
        self.env.user.company_ids |= company
        with self.assertNoLogs("odoo.models", "WARNING"):
            self.env["account.chart.template"].with_company(company).with_context(
                install_module="l10n_be"
            )._create_outstanding_accounts(company, "101", 6)
        self.assertTrue(
            self.env.ref(
                f"account.{company.id}_account_journal_payment_debit_account_id"
            )
        )

    def test_a_chart_load_warns_for_a_foreign_xmlid(self):
        for xmlid, code in (
            ("account.merge_batch2_loud", "990011"),
            ("base.merge_batch2_loud", "990012"),
        ):
            with (
                self.subTest(xmlid=xmlid),
                self.assertLogs("odoo.models", "WARNING") as logs,
            ):
                account = self._chart_load(xmlid, code)
            self.assertEqual(account, self.env.ref(xmlid))
            self.assertEqual(
                logs.output,
                [f"WARNING:odoo.models:Creating record {xmlid} in module l10n_be."],
            )

    def test_a_mixed_chart_load_warns_for_the_foreign_record_alone(self):
        company_xmlid = f"account.{self.env.company.id}_merge_batch2_mixed"
        with self.assertLogs("odoo.models", "WARNING") as logs:
            accounts = (
                self.env["account.chart.template"]
                .with_context(install_module="l10n_be")
                ._load_data(
                    {
                        "account.account": {
                            "merge_batch2_first": {
                                "name": "first",
                                "code": "990001",
                                "account_type": "income",
                            },
                            "base.merge_batch2_second": {
                                "name": "second",
                                "code": "990002",
                                "account_type": "income",
                            },
                            company_xmlid: {
                                "name": "third",
                                "code": "990003",
                                "account_type": "income",
                            },
                        }
                    }
                )["account.account"]
            )
        self.assertEqual(accounts.mapped("name"), ["first", "second", "third"])
        self.assertEqual(
            logs.output,
            [
                "WARNING:odoo.models:Creating record base.merge_batch2_second in module l10n_be."
            ],
        )
