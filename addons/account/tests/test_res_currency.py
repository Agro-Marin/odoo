from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tools import SQL

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestResCurrencyRounding(AccountTestInvoicingCommon):
    """Covers the rounding-change guard on res.currency (account extension)."""

    # The guard keys off the *decimal places* implied by the rounding factor, not
    # the raw factor, because the mapping is non-linear: decimal_places is
    # ceil(log10(1/rounding)) for 0 < rounding < 1, and 0 otherwise.

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.test_currency = cls.env["res.currency"].create(
            {"name": "TES", "symbol": "T", "rounding": 0.01}
        )
        cls.test_currency.write({"active": True})
        cls.env["res.currency.rate"].create(
            {
                "name": "2020-01-01",
                "rate": 2.0,
                "currency_id": cls.test_currency.id,
                "company_id": cls.env.company.id,
            }
        )

    def _give_accounting_entries(self, currency):
        """Create a balanced misc entry whose lines carry ``currency``."""
        # Draft is enough: _has_accounting_entries only counts move lines, so the
        # entry does not need to be posted for the guard to see the currency.
        return self.env["account.move"].create(
            {
                "move_type": "entry",
                "journal_id": self.company_data["default_journal_misc"].id,
                "line_ids": [
                    Command.create(
                        {
                            "account_id": self.company_data[
                                "default_account_revenue"
                            ].id,
                            "debit": 100.0,
                            "credit": 0.0,
                            "currency_id": currency.id,
                            "amount_currency": 200.0,
                        }
                    ),
                    Command.create(
                        {
                            "account_id": self.company_data[
                                "default_account_expense"
                            ].id,
                            "debit": 0.0,
                            "credit": 100.0,
                            "currency_id": currency.id,
                            "amount_currency": -200.0,
                        }
                    ),
                ],
            }
        )

    def test_decimal_places_for_rounding(self):
        currency = self.env["res.currency"]
        cases = {0.01: 2, 0.02: 2, 0.05: 2, 0.1: 1, 0.001: 3, 1.0: 0, 0.0: 0}
        for rounding, expected in cases.items():
            self.assertEqual(
                currency._decimal_places_for_rounding(rounding),
                expected,
                f"rounding {rounding} should imply {expected} decimal places",
            )

    def test_has_accounting_entries(self):
        self.assertFalse(self.test_currency._has_accounting_entries())
        self._give_accounting_entries(self.test_currency)
        self.assertTrue(self.test_currency._has_accounting_entries())

    def test_guard_allows_any_change_without_entries(self):
        # No ledger usage yet: even a genuine place reduction is allowed.
        self.test_currency.write({"rounding": 0.1})
        self.assertEqual(self.test_currency.rounding, 0.1)

    def test_guard_blocks_place_reduction_with_entries(self):
        self._give_accounting_entries(self.test_currency)
        # 0.01 (2 places) -> 0.1 (1 place): a real reduction, must be blocked.
        with self.assertRaises(UserError):
            self.test_currency.write({"rounding": 0.1})

    def test_guard_allows_same_places_with_entries(self):
        # 0.01 -> 0.02 and 0.01 -> 0.05 keep 2 decimal places, so they must be
        # allowed even though the raw factor increases and entries exist.
        self._give_accounting_entries(self.test_currency)
        for rounding in (0.02, 0.05):
            self.test_currency.write({"rounding": rounding})
            self.assertEqual(self.test_currency.rounding, rounding)
            self.test_currency.write({"rounding": 0.01})  # reset

    def test_guard_allows_more_places_with_entries(self):
        # 0.01 (2) -> 0.001 (3): gaining precision is always safe.
        self._give_accounting_entries(self.test_currency)
        self.test_currency.write({"rounding": 0.001})
        self.assertEqual(self.test_currency.rounding, 0.001)

    def test_display_rounding_warning(self):
        # Freshly-loaded record: no pending change, no warning.
        self.assertFalse(self.test_currency.display_rounding_warning)
        edited = self.test_currency.new(
            origin=self.test_currency, values={"rounding": 0.1}
        )
        self.assertTrue(edited.display_rounding_warning)
        # A brand new record (no _origin) never warns.
        fresh = self.env["res.currency"].new({"rounding": 0.1})
        self.assertFalse(fresh.display_rounding_warning)


@tagged("post_install", "-at_install")
class TestResCurrencyTable(AccountTestInvoicingCommon):
    """Covers the reporting currency-table builders."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.other_currency = cls.setup_other_currency("EUR")

    def _fetch_currency_table(self):
        self.env.cr.execute(
            SQL(
                "SELECT company_id, rate_type, rate FROM account_currency_table ORDER BY company_id, rate_type"
            )
        )
        return self.env.cr.fetchall()

    def test_monocurrency_sql_is_all_unit_rates(self):
        # Single-currency set: no temp table, just VALUES with rate 1.
        table_sql = self.env["res.currency"]._get_monocurrency_currency_table_sql(
            self.env.company
        )
        self.env.cr.execute(
            SQL(
                "SELECT company_id, rate_type, rate FROM %s ORDER BY company_id",
                table_sql,
            )
        )
        rows = self.env.cr.fetchall()
        self.assertEqual(rows, [(self.env.company.id, "current", 1)])

    def test_create_table_domestic_only_does_not_crash(self):
        # A company set sharing the main currency yields an empty
        # `other_companies`; the builders must be skipped rather than emitting
        # `IN ()`. The table should still hold a unit rate for the company.
        self.env["res.currency"]._create_currency_table(
            self.env.company, [("period", None, "2020-06-01")]
        )
        rows = self._fetch_currency_table()
        self.assertEqual(rows, [(self.env.company.id, "current", 1)])

    def test_create_table_multicurrency_current_rate(self):
        # A second company on EUR: its 'current' rate must be
        # main_unit_factor / eur_rate as of the period date.
        eur_company = self.env["res.company"].create(
            {"name": "EUR Co", "currency_id": self.other_currency.id}
        )
        companies = self.env.company + eur_company
        date_to = "2020-06-01"
        self.env["res.currency"]._create_currency_table(
            companies, [("period", None, date_to)]
        )
        rows = {
            company_id: rate
            for company_id, _rate_type, rate in self._fetch_currency_table()
        }
        # main company: unit rate
        self.assertEqual(rows[self.env.company.id], 1)
        # EUR company: main_unit_factor / latest EUR rate <= date_to
        main = self.env.company
        main_factor = main.currency_id._get_rates(main, date_to)[main.currency_id.id]
        eur_rate = self.other_currency._get_rates(main, date_to)[self.other_currency.id]
        self.assertAlmostEqual(rows[eur_company.id], main_factor / eur_rate, places=6)

    def test_create_table_cta_builds_all_rate_types(self):
        # use_cta_rates=True exercises the historical and average builders (and
        # their scope plumbing). The domestic company gets a unit rate of every
        # type; the EUR company gets current/historical/average rows.
        eur_company = self.env["res.company"].create(
            {"name": "EUR Co", "currency_id": self.other_currency.id}
        )
        self.env["res.currency"]._create_currency_table(
            self.env.company + eur_company,
            [("period", "2016-01-01", "2020-06-01")],
            use_cta_rates=True,
        )
        rate_types = {
            (company_id, rate_type)
            for company_id, rate_type, _rate in self._fetch_currency_table()
        }
        for company in (self.env.company.id, eur_company.id):
            for rate_type in ("current", "historical", "average"):
                self.assertIn((company, rate_type), rate_types)

    def test_create_table_current_rate_falls_back_to_parity(self):
        # Documented divergence from _get_rates: a currency with no rate on or
        # before the period date is treated at parity (rate 1) in the report
        # table. This test pins that behaviour so it is not changed by accident.
        future_currency = self.env["res.currency"].create(
            {"name": "FUT", "symbol": "F", "rounding": 0.01}
        )
        self.env["res.currency.rate"].create(
            {
                "name": "2030-01-01",
                "rate": 5.0,
                "currency_id": future_currency.id,
                "company_id": self.env.company.id,
            }
        )
        fut_company = self.env["res.company"].create(
            {"name": "FUT Co", "currency_id": future_currency.id}
        )
        self.env["res.currency"]._create_currency_table(
            self.env.company + fut_company, [("period", None, "2020-06-01")]
        )
        rows = {
            company_id: rate
            for company_id, _rate_type, rate in self._fetch_currency_table()
        }
        self.assertEqual(rows[fut_company.id], 1)
