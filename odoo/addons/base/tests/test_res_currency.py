from lxml import etree

from odoo import Command
from odoo.tests.common import TransactionCase


class TestResCurrency(TransactionCase):
    def test_view_company_rate_label(self):
        """The company_rate / inverse_company_rate labels follow the company
        currency, e.g. `Unit per EUR` for a company using EUR.
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

        self.env["res.currency.rate"].search(
            [("currency_id", "=", currencyB.id), ("name", "=", "2009-09-09")]
        ).rate = 3

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

        self.env["res.currency.rate"].create(
            {
                "name": "2010-10-10",
                "rate": 4,
                "currency_id": currencyB.id,
                "company_id": self.env.company.id,
            }
        )

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

        with self.assertQueryCount(0):
            self.assertEqual(
                currencyA._convert(
                    from_amount=100,
                    to_currency=currencyB,
                    company=self.env.company,
                    date="2011-11-11",
                ),
                200,
            )

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
        self.assertEqual(
            source._convert(10.0, target, self.env.company, "2010-10-10"), 30.0
        )
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
        self.assertEqual(
            source._convert(10.5, target, self.env.company, "2010-10-10", round=False),
            31.5,
        )
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
        self.assertEqual(
            source._convert(100, target, self.env.company, "2011-11-11"), 500
        )
        self.assertEqual(
            source._convert(100, target, self.env.company, "2011-11-10"), 200
        )

    def test_convert_no_rate_uses_earliest_then_identity(self):
        """RCUR-T1 / RCUR-L1: a date before the first rate uses the earliest rate;
        a currency with no rate at all uses the COALESCE -> 1.0 identity path.
        """
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
        no_rate = self.env["res.currency"].create({"name": "NR1", "symbol": "N1"})
        self.assertFalse(no_rate.rate_ids)
        self.assertEqual(
            company_currency._convert(100, no_rate, self.env.company, "2010-10-10"),
            100,
        )

    def test_rate_memo_distinct_dates_single_query(self):
        """RCUR-M1: the first lookup for a currency loads its full rate history
        in one query; further conversions at any distinct dates in the same
        transaction are answered from the memo without SQL.
        """
        cur_a, cur_b = self.env["res.currency"].create(
            [
                {
                    "name": "MA1",
                    "symbol": "MA",
                    "rate_ids": [Command.create({"name": "2020-01-01", "rate": 1})],
                },
                {
                    "name": "MB1",
                    "symbol": "MB",
                    "rate_ids": [
                        Command.create({"name": "2020-01-01", "rate": 2}),
                        Command.create({"name": "2020-02-01", "rate": 3}),
                        Command.create({"name": "2020-03-01", "rate": 4}),
                    ],
                },
            ]
        )
        company = self.env.company
        company.currency_id._convert(1.0, cur_a, company, "2020-06-15")
        (cur_a + cur_b).mapped("rounding")
        with self.assertQueryCount(1):
            self.assertEqual(cur_a._convert(100, cur_b, company, "2020-01-20"), 200)
            self.assertEqual(cur_a._convert(100, cur_b, company, "2020-02-15"), 300)
            self.assertEqual(cur_a._convert(100, cur_b, company, "2020-03-15"), 400)
            self.assertEqual(cur_a._convert(100, cur_b, company, "2019-06-15"), 200)
            for day in range(1, 29):
                cur_a._convert(100, cur_b, company, f"2020-02-{day:02d}")

    def test_rate_memo_company_scoping_matches_sql(self):
        """RCUR-M1: the memoized lookup returns exactly what the SQL cold
        path returns for every (company, date) combination — including
        company-root vs global scope precedence, the pre-history
        earliest-rate fallback, NULL-valued rate rows and the 1.0 identity.
        """
        company_a = self.env.company
        company_b = self.env["res.company"].create({"name": "memo scope co"})
        cur_x, cur_y, cur_z = self.env["res.currency"].create(
            [
                {"name": "MX1", "symbol": "X"},
                {"name": "MY1", "symbol": "Y"},
                {"name": "MZ1", "symbol": "Z"},
            ]
        )
        self.env["res.currency.rate"].create(
            [
                {
                    "name": "2020-01-01",
                    "rate": 2,
                    "currency_id": cur_x.id,
                    "company_id": False,
                },
                {
                    "name": "2021-03-01",
                    "rate": 3,
                    "currency_id": cur_x.id,
                    "company_id": False,
                },
                {
                    "name": "2021-01-01",
                    "rate": 5,
                    "currency_id": cur_x.id,
                    "company_id": company_b.id,
                },
                {
                    "name": "2019-01-01",
                    "rate": 7,
                    "currency_id": cur_y.id,
                    "company_id": False,
                },
                {"name": "2020-01-01", "currency_id": cur_y.id, "company_id": False},
            ]
        )
        currencies = cur_x + cur_y + cur_z
        for company in (company_a, company_b):
            for date in ("2018-06-01", "2020-06-01", "2021-02-01", "2021-06-01"):
                self.assertEqual(
                    currencies._get_rates(company, date),
                    currencies._get_rates_sql(company, date),
                    f"memo/SQL divergence for {company.name} at {date}",
                )
        rates_a = currencies._get_rates(company_a, "2021-06-01")
        rates_b = currencies._get_rates(company_b, "2021-06-01")
        self.assertEqual(rates_b[cur_x.id], 5)
        self.assertEqual(rates_a[cur_x.id], 3)
        self.assertEqual(rates_a[cur_y.id], 7)
        self.assertEqual(rates_a[cur_z.id], 1.0)
        self.assertEqual(currencies._get_rates(company_b, "2018-06-01")[cur_x.id], 5)
        self.assertEqual(currencies._get_rates(company_a, "2018-06-01")[cur_x.id], 2)

    def test_rate_memo_invalidated_within_transaction(self):
        """RCUR-M1: rate create/write/unlink within the same transaction drop
        the memo (and the cross-record inverse_rate cache), so conversions
        immediately see the change.
        """
        cur_a, cur_b = self.env["res.currency"].create(
            [
                {
                    "name": "MI1",
                    "symbol": "IA",
                    "rate_ids": [Command.create({"name": "2020-01-01", "rate": 1})],
                },
                {
                    "name": "MI2",
                    "symbol": "IB",
                    "rate_ids": [Command.create({"name": "2020-01-01", "rate": 2})],
                },
            ]
        )
        company = self.env.company

        def convert(date):
            return cur_a._convert(100, cur_b, company, date)

        self.assertEqual(convert("2020-06-01"), 200)
        cur_b.rate_ids.rate = 4
        self.assertEqual(convert("2020-06-01"), 400)
        self.env["res.currency.rate"].create(
            {
                "name": "2020-03-01",
                "rate": 8,
                "currency_id": cur_b.id,
                "company_id": company.id,
            }
        )
        self.assertEqual(convert("2020-06-01"), 800)
        self.assertEqual(convert("2020-02-01"), 400)
        cur_b.rate_ids.filtered(lambda r: str(r.name) == "2020-03-01").unlink()
        self.assertEqual(convert("2020-06-01"), 400)

    def test_rate_date_and_company_change_invalidate_currency_cache(self):
        """RCUR-C1: changing a rate's date or company within a transaction must
        refresh the currency's cached rate/rate_string, not only inverse_rate.

        The newest rate is picked by sorting rather than by ``rate_ids[0]``:
        records created through an inline command stay in the field's cache in
        creation order until something flushes and re-reads them, so the
        ``_order`` of ``res.currency.rate`` ("name desc") does not apply yet.
        Whether a flush happens in between depends on unrelated state, which
        made this test pass or fail by accident.
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
        newest = currency.rate_ids.sorted("name", reverse=True)[0]
        self.assertEqual(str(newest.name), "2020-03-01")
        rate_before = currency.rate
        newest.name = "2020-12-31"
        self.assertAlmostEqual(currency.rate, rate_before / 2)
        self.assertIn(f"{rate_before / 2:.6f}", currency.rate_string)
        newest.name = "2020-03-01"
        self.assertAlmostEqual(currency.rate, rate_before)
        other_company = self.env["res.company"].create({"name": "other"})
        newest.company_id = other_company
        self.assertAlmostEqual(currency.rate, rate_before / 2)

    def test_rate_change_of_company_currency_invalidates_other_currencies(self):
        """RCUR-C2: rate/inverse_rate/rate_string of a currency are computed
        against the company currency's own rate rows — a cross-record
        dependency @api.depends cannot express.  Creating, writing or deleting
        a rate of the *company* currency must therefore invalidate all three
        fields model-wide, not only inverse_rate.
        """
        company_currency, other = self.env["res.currency"].create(
            [
                {"name": "CMX", "symbol": "M"},
                {"name": "CXX", "symbol": "X"},
            ]
        )
        company = self.env["res.company"].create(
            {"name": "rate invalidation co", "currency_id": company_currency.id}
        )
        company_rate = self.env["res.currency.rate"].create(
            {
                "name": "2020-01-01",
                "rate": 20,
                "currency_id": company_currency.id,
                "company_id": company.id,
            }
        )
        self.env["res.currency.rate"].create(
            {
                "name": "2020-01-01",
                "rate": 2,
                "currency_id": other.id,
                "company_id": company.id,
            }
        )
        other = other.with_company(company).with_context(date="2020-06-01")

        self.assertAlmostEqual(other.rate, 2 / 20)
        self.assertIn(f"{2 / 20:.6f}", other.rate_string)

        company_rate.rate = 10
        self.assertAlmostEqual(other.rate, 2 / 10)
        self.assertAlmostEqual(other.inverse_rate, 10 / 2)
        self.assertIn(f"{2 / 10:.6f}", other.rate_string)

        newer = self.env["res.currency.rate"].create(
            {
                "name": "2020-03-01",
                "rate": 4,
                "currency_id": company_currency.id,
                "company_id": company.id,
            }
        )
        self.assertAlmostEqual(other.rate, 2 / 4)
        self.assertIn(f"{2 / 4:.6f}", other.rate_string)

        newer.unlink()
        self.assertAlmostEqual(other.rate, 2 / 10)
        self.assertIn(f"{2 / 10:.6f}", other.rate_string)

    def test_sanitize_vals_does_not_mutate_caller_dict(self):
        """RCUR-S1: redundant rate encodings are dropped from a copy; the
        caller-owned vals dict is left untouched by create() and write().
        """
        currency = self.env["res.currency"].create({"name": "SAN", "symbol": "S"})
        create_vals = {
            "name": "2020-01-01",
            "rate": 2.0,
            "company_rate": 999.0,
            "inverse_company_rate": 999.0,
            "currency_id": currency.id,
            "company_id": self.env.company.id,
        }
        create_vals_copy = dict(create_vals)
        rate = self.env["res.currency.rate"].create(create_vals)
        self.assertEqual(create_vals, create_vals_copy)
        self.assertAlmostEqual(rate.rate, 2.0)

        write_vals = {"rate": 3.0, "company_rate": 123.0}
        write_vals_copy = dict(write_vals)
        rate.write(write_vals)
        self.assertEqual(write_vals, write_vals_copy)
        self.assertAlmostEqual(rate.rate, 3.0)

    def test_company_rate_history_fallbacks(self):
        """RCUR-P1: company_rate uses the record's own rate, else the latest
        rate strictly before its date, else the identity rate 1.0.
        """
        currency = self.env["res.currency"].create({"name": "DDD", "symbol": "D"})
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
        self.assertAlmostEqual(rate_new.company_rate, 1.0)
        self.assertAlmostEqual(rate_old.company_rate, 0.5)
        empty_between = self.env["res.currency.rate"].create(
            {
                "name": "2020-01-15",
                "currency_id": currency.id,
                "company_id": company.id,
            }
        )
        self.assertAlmostEqual(empty_between.company_rate, 2 / 4)
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
        self.assertEqual(
            self.env["res.currency"].search_count([["rate_ids", "=", "1971-01-01"]]),
            2,
        )
        self.assertEqual(
            self.env["res.currency"].search_count([["rate_ids", "=", "0.69"]]),
            1,
        )
        self.assertEqual(
            self.env["res.currency"].search_count([["rate_ids", "=", "irrelevant"]]),
            0,
        )


class TestResCurrencyRateMemoScope(TransactionCase):
    """RCUR-M1: the rate memo must not be shared across access contexts.

    ``_get_rates_from_memo`` populates itself with a rule-filtered query, so
    its result depends on the reader. Keyed on ``(currency, company root)``
    alone, whichever context first touched a currency answered for every later
    one in the same transaction, diverging from ``_get_rates_sql`` in both
    directions. The parity test above cannot see this: it runs as a single
    user, where rules apply identically to both paths.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.env["res.company"].create({"name": "memo scope A"})
        cls.company_b = cls.env["res.company"].create({"name": "memo scope B"})
        cls.currency = cls.env["res.currency"].create(
            {"name": "MS1", "symbol": "MS", "rounding": 0.01}
        )
        cls.env["res.currency.rate"].create(
            {
                "currency_id": cls.currency.id,
                "company_id": cls.company_b.id,
                "name": "2020-01-01",
                "rate": 7.0,
            }
        )
        cls.user = cls.env["res.users"].create(
            {
                "name": "memo scope user",
                "login": "memo_scope_user",
                "company_id": cls.company_a.id,
                "company_ids": [Command.set(cls.company_a.ids)],
                "group_ids": [Command.set(cls.env.ref("base.group_user").ids)],
            }
        )
        cls.env.flush_all()

    def _rates(self, su, sql=False):
        env = self.env(
            user=self.user, su=su, context={"allowed_company_ids": self.company_a.ids}
        )
        currency = env["res.currency"].browse(self.currency.id)
        company = env["res.company"].browse(self.company_b.id)
        method = currency._get_rates_sql if sql else currency._get_rates
        return method(company, "2020-06-01")[self.currency.id]

    def test_reference_paths_differ_by_access_context(self):
        """The premise: the rule genuinely hides company B's rate here."""
        self.assertEqual(self._rates(True, sql=True), 7.0)
        self.assertEqual(self._rates(False, sql=True), 1.0)

    def test_restricted_reader_after_sudo_does_not_inherit_the_hidden_rate(self):
        self.assertEqual(self._rates(True), 7.0)
        self.assertEqual(self._rates(False), 1.0)

    def test_sudo_after_restricted_reader_is_not_pinned_to_the_restricted_set(self):
        self.assertEqual(self._rates(False), 1.0)
        self.assertEqual(self._rates(True), 7.0)

    def test_memo_matches_sql_for_every_access_context(self):
        for su in (True, False):
            self.assertEqual(
                self._rates(su),
                self._rates(su, sql=True),
                f"memo/SQL divergence for su={su}",
            )
