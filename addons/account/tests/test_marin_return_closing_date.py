from freezegun import freeze_time

from odoo import Command, fields
from odoo.tests import tagged

from odoo.addons.account.tests.common_report_engine import TestAccountReportsCommon


@tagged("post_install", "-at_install")
class TestMarinReturnClosingDate(TestAccountReportsCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.startClassPatcher(freeze_time("2026-03-15"))
        cls.annual_return = (
            cls.env.ref("account.annual_corporate_tax_return_type")
            .with_context(
                forced_date_from=fields.Date.from_string("2025-01-01"),
                forced_date_to=fields.Date.from_string("2025-12-31"),
            )
            ._try_create_returns_for_fiscal_year(cls.company_data["company"], False)
        )

    def _post_entry(self, date, account, balance, partner=None):
        move = self.env["account.move"].create(
            {
                "move_type": "entry",
                "date": date,
                "journal_id": self.company_data["default_journal_misc"].id,
                "line_ids": [
                    Command.create(
                        {
                            "name": "open item",
                            "balance": balance,
                            "account_id": account.id,
                            "partner_id": partner.id if partner else False,
                            "date_maturity": date,
                        }
                    ),
                    Command.create(
                        {
                            "name": "counterpart",
                            "balance": -balance,
                            "account_id": self.company_data[
                                "default_account_revenue"
                            ].id,
                        }
                    ),
                ],
            }
        )
        move.action_post()
        return move.line_ids.filtered(lambda line: line.account_id == account)

    def _open_item(self, kind, date, partner=None, settled_on=None):
        account, sign = {
            "receivable": (self.company_data["default_account_receivable"], 1),
            "payable": (self.company_data["default_account_payable"], -1),
        }[kind]
        line = self._post_entry(date, account, sign * 100.0, partner)
        if settled_on:
            (
                line + self._post_entry(settled_on, account, -sign * 100.0, partner)
            ).reconcile()

    def _results(self):
        return {
            check["code"]: check["result"]
            for check in self.annual_return._check_suite_annual_closing(set())
        }

    def test_items_opened_after_period_end_are_not_flagged(self):
        for kind in ("receivable", "payable"):
            self._open_item(kind, "2025-12-20", partner=self.partner_a)
            self._open_item(kind, "2026-01-10")
        results = self._results()
        for kind in ("receivables", "payables"):
            with self.subTest(kind=kind):
                self.assertEqual(results[f"check_overdue_{kind}"], "reviewed")
                self.assertEqual(results[f"check_unkown_partner_{kind}"], "reviewed")

    def test_items_open_at_period_end_but_settled_since_are_flagged(self):
        for kind in ("receivable", "payable"):
            self._open_item(
                kind, "2025-09-01", partner=self.partner_a, settled_on="2026-02-01"
            )
            self._open_item(kind, "2025-06-01", settled_on="2026-02-01")
        results = self._results()
        for kind in ("receivables", "payables"):
            with self.subTest(kind=kind):
                self.assertEqual(results[f"check_overdue_{kind}"], "anomaly")
                self.assertEqual(results[f"check_unkown_partner_{kind}"], "anomaly")

    def test_overdue_review_opens_the_aged_report_at_period_end(self):
        self._open_item("receivable", "2025-09-01", partner=self.partner_a)
        check = next(
            check
            for check in self.annual_return._check_suite_annual_closing(set())
            if check["code"] == "check_overdue_receivables"
        )
        report = self.env.ref("account.aged_receivable_report")
        options = report.with_context(**check["action"]["context"]).get_options(
            check["action"]["params"]["options"]
        )
        self.assertEqual(
            (options["date"]["mode"], options["date"]["date_to"]),
            ("single", "2025-12-31"),
        )
        self.assertEqual(
            [company["id"] for company in options["companies"]],
            self.annual_return.company_id.ids,
        )
