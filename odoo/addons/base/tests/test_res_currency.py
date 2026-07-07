from lxml import etree

from odoo import Command
from odoo.tests.common import TransactionCase


class TestResCurrency(TransactionCase):
    def test_view_company_rate_label(self):
        """Tests the label of the company_rate and inverse_company_rate fields
        are well set according to the company currency in the currency form view and the currency rate list view.
        e.g. in the currency rate list view of a company using EUR, the company_rate label must be `Unit per EUR`
        """
        company_foo, company_bar = self.env["res.company"].create(
            [
                {"name": "foo", "currency_id": self.env.ref("base.EUR").id},
                {"name": "bar", "currency_id": self.env.ref("base.USD").id},
            ]
        )
        for company, expected_currency in [
            (company_foo, "EUR"),
            (company_bar, "USD"),
        ]:
            for model, view_type in [
                ("res.currency", "form"),
                ("res.currency.rate", "list"),
            ]:
                arch = (
                    self.env[model]
                    .with_company(company)
                    .get_view(view_type=view_type)["arch"]
                )
                tree = etree.fromstring(arch)
                node_company_rate = tree.find('.//field[@name="company_rate"]')
                node_inverse_company_rate = tree.find(
                    './/field[@name="inverse_company_rate"]'
                )
                self.assertEqual(
                    node_company_rate.get("string"),
                    f"Unit per {expected_currency}",
                )
                self.assertEqual(
                    node_inverse_company_rate.get("string"),
                    f"{expected_currency} per Unit",
                )

    def test_currency_cache(self):
        currencyA, currencyB = self.env["res.currency"].create(
            [
                {
                    "name": "AAA",
                    "symbol": "AAA",
                    "rate_ids": [Command.create({"name": "2009-09-09", "rate": 1})],
                },
                {
                    "name": "BBB",
                    "symbol": "BBB",
                    "rate_ids": [
                        Command.create({"name": "2009-09-09", "rate": 1}),
                        Command.create({"name": "2011-11-11", "rate": 2}),
                    ],
                },
            ]
        )

        self.assertEqual(
            currencyA._convert(
                from_amount=100,
                to_currency=currencyB,
                company=self.env.company,
                date="2010-10-10",
            ),
            100,
        )

        # update the (cached) rate of the to_currency used in the previous query
        self.env["res.currency.rate"].search(
            [("currency_id", "=", currencyB.id), ("name", "=", "2009-09-09")]
        ).rate = 3

        # repeat _convert call
        # the cached conversion rate is invalid due to the rate change -> query
        with self.assertQueryCount(1):
            self.assertEqual(
                currencyA._convert(
                    from_amount=100,
                    to_currency=currencyB,
                    company=self.env.company,
                    date="2010-10-10",
                ),
                300,
            )

        # create a new rate of the to_currency for the date used in the previous query
        self.env["res.currency.rate"].create(
            {
                "name": "2010-10-10",
                "rate": 4,
                "currency_id": currencyB.id,
                "company_id": self.env.company.id,
            }
        )

        # repeat _convert call
        # the cached conversion rate is invalid due to the new rate of the to_currency -> query
        with self.assertQueryCount(1):
            self.assertEqual(
                currencyA._convert(
                    from_amount=100,
                    to_currency=currencyB,
                    company=self.env.company,
                    date="2010-10-10",
                ),
                400,
            )

        # only one query is done when changing the convert params
        with self.assertQueryCount(1):
            self.assertEqual(
                currencyA._convert(
                    from_amount=100,
                    to_currency=currencyB,
                    company=self.env.company,
                    date="2011-11-11",
                ),
                200,
            )

        # cache holds multiple values
        with self.assertQueryCount(0):
            self.assertEqual(
                currencyA._convert(
                    from_amount=100,
                    to_currency=currencyB,
                    company=self.env.company,
                    date="2010-10-10",
                ),
                400,
            )
            self.assertEqual(
                currencyA._convert(
                    from_amount=100,
                    to_currency=currencyB,
                    company=self.env.company,
                    date="2011-11-11",
                ),
                200,
            )

    def test_convert_rounding_to_target_precision(self):
        """RCUR-T1: _convert rounds the result to the target currency precision."""
        # Source 2-dp, target 0-dp (rounding factor 1.0 → 0 decimal places).
        source, target = self.env["res.currency"].create(
            [
                {
                    "name": "SRC",
                    "symbol": "S",
                    "rounding": 0.01,
                    "rate_ids": [Command.create({"name": "2009-09-09", "rate": 1})],
                },
                {
                    "name": "TGT",
                    "symbol": "T",
                    "rounding": 1.0,
                    "rate_ids": [Command.create({"name": "2009-09-09", "rate": 3})],
                },
            ]
        )
        self.assertEqual(target.decimal_places, 0)
        # 10.0 * 3 = 30.0 → rounded to 0-dp target stays 30.0
        self.assertEqual(
            source._convert(10.0, target, self.env.company, "2010-10-10"), 30.0
        )
        # A value that would carry fractions: 10.5 * 3 = 31.5 → 0-dp rounds to 32.0
        self.assertEqual(
            source._convert(10.5, target, self.env.company, "2010-10-10"), 32.0
        )

    def test_convert_round_false_returns_unrounded(self):
        """RCUR-T1: round=False returns the raw (unrounded) converted amount."""
        source, target = self.env["res.currency"].create(
            [
                {
                    "name": "SR2",
                    "symbol": "S2",
                    "rounding": 0.01,
                    "rate_ids": [Command.create({"name": "2009-09-09", "rate": 1})],
                },
                {
                    "name": "TG2",
                    "symbol": "T2",
                    "rounding": 1.0,
                    "rate_ids": [Command.create({"name": "2009-09-09", "rate": 3})],
                },
            ]
        )
        # 10.5 * 3 = 31.5; with round=False the fractional part survives.
        self.assertEqual(
            source._convert(10.5, target, self.env.company, "2010-10-10", round=False),
            31.5,
        )
        # With round=True the same conversion rounds to the 0-dp target.
        self.assertEqual(
            source._convert(10.5, target, self.env.company, "2010-10-10", round=True),
            32.0,
        )

    def test_convert_rate_date_boundary(self):
        """RCUR-T1: _convert picks the latest rate with name <= date."""
        source, target = self.env["res.currency"].create(
            [
                {
                    "name": "SR3",
                    "symbol": "S3",
                    "rate_ids": [Command.create({"name": "2009-09-09", "rate": 1})],
                },
                {
                    "name": "TG3",
                    "symbol": "T3",
                    "rate_ids": [
                        Command.create({"name": "2009-09-09", "rate": 2}),
                        Command.create({"name": "2011-11-11", "rate": 5}),
                    ],
                },
            ]
        )
        # Exactly on the later boundary -> the 2011 rate (5) applies.
        self.assertEqual(
            source._convert(100, target, self.env.company, "2011-11-11"), 500
        )
        # The day before the later boundary -> still the earlier rate (2).
        self.assertEqual(
            source._convert(100, target, self.env.company, "2011-11-10"), 200
        )

    def test_convert_no_rate_uses_earliest_then_identity(self):
        """RCUR-T1 / RCUR-L1: a date before the first rate uses the earliest rate;
        a currency with no rate at all uses the COALESCE -> 1.0 identity path.
        """
        # Currency with a single rate dated 2011: a 2010 date precedes it and
        # must fall back to that earliest known rate (RCUR-L1).
        with_rate = self.env["res.currency"].create(
            {
                "name": "WR1",
                "symbol": "W1",
                "rate_ids": [Command.create({"name": "2011-11-11", "rate": 4})],
            }
        )
        company_currency = self.env.company.currency_id
        self.assertEqual(
            company_currency._convert(100, with_rate, self.env.company, "2010-10-10"),
            400,
        )
        # Currency with NO rate at all -> COALESCE(..., 1.0) identity rate.
        no_rate = self.env["res.currency"].create({"name": "NR1", "symbol": "N1"})
        self.assertFalse(no_rate.rate_ids)
        self.assertEqual(
            company_currency._convert(100, no_rate, self.env.company, "2010-10-10"),
            100,
        )

    def test_rate_date_and_company_change_invalidate_currency_cache(self):
        """RCUR-C1: changing a rate's date or company within a transaction must
        refresh the currency's cached rate/rate_string, not only inverse_rate.
        """
        currency = self.env["res.currency"].create(
            {
                "name": "CCC",
                "symbol": "C",
                "rate_ids": [
                    Command.create({"name": "2020-01-01", "rate": 2}),
                    Command.create({"name": "2020-03-01", "rate": 4}),
                ],
            }
        )
        currency = currency.with_context(date="2020-06-06")
        newest = currency.rate_ids[0]  # rate_ids is ordered "name desc, id"
        self.assertEqual(str(newest.name), "2020-03-01")
        rate_before = currency.rate
        # Move the newest rate past the lookup date: only the 2020-01-01 rate
        # (half the value) applies; the cached rate must follow.
        newest.name = "2020-12-31"
        self.assertAlmostEqual(currency.rate, rate_before / 2)
        self.assertIn(f"{rate_before / 2:.6f}", currency.rate_string)
        # Move it back: the cached value must follow again.
        newest.name = "2020-03-01"
        self.assertAlmostEqual(currency.rate, rate_before)
        # Rescope it to another company: it no longer applies to env.company.
        other_company = self.env["res.company"].create({"name": "other"})
        newest.company_id = other_company
        self.assertAlmostEqual(currency.rate, rate_before / 2)

    def test_company_rate_history_fallbacks(self):
        """RCUR-P1: company_rate uses the record's own rate, else the latest
        rate strictly before its date, else the identity rate 1.0.
        """
        currency = self.env["res.currency"].create({"name": "DDD", "symbol": "D"})
        # company_rate is expressed against the last rate of the *company's*
        # currency: use a company whose currency is the tested one so that
        # divisor is the currency's own latest rate (4).
        company = self.env["res.company"].create(
            {"name": "company DDD", "currency_id": currency.id}
        )
        rate_old, rate_new = self.env["res.currency.rate"].create(
            [
                {
                    "name": "2020-01-01",
                    "rate": 2,
                    "currency_id": currency.id,
                    "company_id": company.id,
                },
                {
                    "name": "2020-02-01",
                    "rate": 4,
                    "currency_id": currency.id,
                    "company_id": company.id,
                },
            ]
        )
        # The last rate of the company's currency is 4 -> company_rate = rate / 4.
        self.assertAlmostEqual(rate_new.company_rate, 1.0)
        self.assertAlmostEqual(rate_old.company_rate, 0.5)
        # A valueless rate falls back to the latest rate before its date (2).
        empty_between = self.env["res.currency.rate"].create(
            {
                "name": "2020-01-15",
                "currency_id": currency.id,
                "company_id": company.id,
            }
        )
        self.assertAlmostEqual(empty_between.company_rate, 2 / 4)
        # A valueless rate with no earlier rate falls back to 1.0.
        empty_first = self.env["res.currency.rate"].create(
            {
                "name": "2019-01-01",
                "currency_id": currency.id,
                "company_id": company.id,
            }
        )
        self.assertAlmostEqual(empty_first.company_rate, 1 / 4)

    def test_amount_to_text_unsupported_lang_falls_back_with_warning(self):
        """RCUR-T2: an iso_code unknown to num2words falls back to English
        words and logs a warning naming the missing language.
        """
        self.env["res.lang"].create(
            {
                "name": "Klingon",
                "code": "tlh_TLH",
                "iso_code": "tlh",
                "url_code": "tlh",
                "active": True,
            }
        )
        currency = self.env.ref("base.USD")
        with self.assertLogs(
            "odoo.addons.base.models.res_currency", level="WARNING"
        ) as capture:
            text = currency.with_context(lang="tlh_TLH").amount_to_text(1.0)
        self.assertIn("One", text)
        self.assertIn("'tlh'", capture.output[0])

    def test_amount_to_text_negative(self):
        """RCUR-T2: amount_to_text on an amount in (-1, 0) keeps the sign."""
        currency = self.env.ref("base.USD")
        text = currency.amount_to_text(-0.5)
        self.assertTrue(
            text.startswith("Minus"),
            f"expected a 'Minus' prefix for a negative sub-unit amount, got {text!r}",
        )

    def test_res_currency_name_search(self):
        currency_A, currency_B = self.env["res.currency"].create(
            [
                {"name": "cuA", "symbol": "A"},
                {"name": "cuB", "symbol": "B"},
            ]
        )
        self.env["res.currency.rate"].create(
            [
                {
                    "name": "1971-01-01",
                    "rate": 2.0,
                    "currency_id": currency_A.id,
                },
                {
                    "name": "1971-01-01",
                    "rate": 1.5,
                    "currency_id": currency_B.id,
                },
                {
                    "name": "1972-01-01",
                    "rate": 0.69,
                    "currency_id": currency_B.id,
                },
            ]
        )
        # should not try to match field 'name' (date field)
        self.assertEqual(
            self.env["res.currency"].search_count([["rate_ids", "=", "1971-01-01"]]),
            2,
        )
        # should not try to match field 'rate' (float field)
        self.assertEqual(
            self.env["res.currency"].search_count([["rate_ids", "=", "0.69"]]),
            1,
        )
        # should not try to match any of 'name' and 'rate'
        self.assertEqual(
            self.env["res.currency"].search_count([["rate_ids", "=", "irrelevant"]]),
            0,
        )
