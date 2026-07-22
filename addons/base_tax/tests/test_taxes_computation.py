"""Standalone regression tests for the ``base_tax`` computation engine.

The ``account`` module exercises this engine extensively, but only ever with the
full accounting stack installed.  ``base_tax`` ships independently and promises
"tax computation without the full accounting stack".  The code paths that make
that promise work are the runtime seams that fall back when accounting fields are
absent, e.g.::

    "tax_calculation_rounding_method" in company._fields  # -> round_per_line
    "account_price_include" in company._fields  # -> company_price_include = False
    "account_fiscal_country_id" in company._fields  # -> country from company_id.country_id

Those seams are only ever taken when ``account`` is NOT installed, so nothing
tests them today.  This suite pins the engine's behaviour standalone.  It also
runs (harmlessly) when ``account`` is installed; the few assertions that are
specific to the standalone fallbacks skip themselves in that case.
"""

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestBaseTaxComputation(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        # A tax needs a (non-null) country and tax group; base_tax ships neither,
        # so seed them explicitly to keep the tests deterministic in both the
        # standalone and account-installed environments.
        # Derive the country from the company (US only as fallback) and pin it
        # on the group explicitly: hardcoding base.us broke on databases whose
        # company already has a country (the group defaults to it and the
        # country-consistency constraint rejects the mismatch).
        cls.country = cls.company.country_id or cls.env.ref("base.us")
        if not cls.company.country_id:
            cls.company.country_id = cls.country
        cls.tax_group = cls.env["account.tax.group"].create(
            {
                "name": "base_tax test group",
                "company_id": cls.company.id,
                "country_id": cls.country.id,
            }
        )
        cls.currency = cls.company.currency_id
        cls.account_installed = (
            "tax_calculation_rounding_method" in cls.env["res.company"]._fields
        )

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    _seq = 0

    @classmethod
    def _tax(cls, amount, amount_type="percent", **kw):
        cls._seq += 1
        kw.setdefault("name", f"BT test tax {cls._seq}")
        kw.setdefault("type_tax_use", "sale")
        kw.setdefault("country_id", cls.country.id)
        kw.setdefault("tax_group_id", cls.tax_group.id)
        return cls.env["account.tax"].create(
            {"amount_type": amount_type, "amount": amount, **kw}
        )

    def _base_line(self, taxes, price_unit, quantity=1.0, **kw):
        return self.env["account.tax"]._prepare_base_line_for_taxes_computation(
            None,
            company_id=self.company,
            currency_id=self.currency,
            tax_ids=taxes,
            price_unit=price_unit,
            quantity=quantity,
            **kw,
        )

    # ------------------------------------------------------------------
    # standalone seams
    # ------------------------------------------------------------------
    def test_standalone_seams_absent_without_account(self):
        """The accounting fields the engine probes for must be absent standalone."""
        if self.account_installed:
            self.skipTest("account installed: standalone fallbacks not exercised")
        company_fields = self.env["res.company"]._fields
        self.assertNotIn("tax_calculation_rounding_method", company_fields)
        self.assertNotIn("account_price_include", company_fields)
        self.assertNotIn("account_fiscal_country_id", company_fields)
        # company_price_include falls back to False, so price_include follows
        # only the per-tax override.
        tax = self._tax(21.0)
        self.assertFalse(tax.company_price_include)
        self.assertFalse(tax.price_include)
        tax_incl = self._tax(21.0, price_include_override="tax_included")
        self.assertTrue(tax_incl.price_include)

    def test_default_rounding_is_round_per_line_standalone(self):
        """Without a company rounding-method field, the engine rounds per line."""
        if self.account_installed:
            self.skipTest("account installed: company drives the rounding method")
        tax = self._tax(21.0)
        base_line = self._base_line(tax, 21.53, quantity=2.0)
        # No explicit rounding_method -> falls back to round_per_line.
        self.env["account.tax"]._add_tax_details_in_base_line(base_line, self.company)
        # round_per_line rounds each line's amounts to currency precision.
        tax_data = base_line["tax_details"]["taxes_data"][0]
        self.assertEqual(tax_data["raw_tax_amount"], self.currency.round(43.06 * 0.21))

    # ------------------------------------------------------------------
    # compute_all
    # ------------------------------------------------------------------
    def test_compute_all_percent_excluded(self):
        tax = self._tax(21.0)
        res = tax.compute_all(100.0)
        self.assertEqual(res["total_excluded"], 100.0)
        self.assertEqual(res["total_included"], 121.0)
        self.assertEqual(len(res["taxes"]), 1)
        self.assertEqual(res["taxes"][0]["amount"], 21.0)
        self.assertEqual(res["taxes"][0]["base"], 100.0)

    def test_compute_all_percent_included(self):
        tax = self._tax(21.0, price_include_override="tax_included")
        res = tax.compute_all(121.0)
        self.assertEqual(res["total_excluded"], 100.0)
        self.assertEqual(res["total_included"], 121.0)

    def test_compute_all_fixed(self):
        tax = self._tax(5.0, amount_type="fixed")
        res = tax.compute_all(100.0, quantity=3.0)
        # base 300 + fixed 5 * 3 = 315
        self.assertEqual(res["total_included"], 315.0)

    def test_compute_all_fixed_negative_price_flips_sign(self):
        tax = self._tax(5.0, amount_type="fixed")
        res = tax.compute_all(-100.0, quantity=3.0)
        self.assertEqual(res["taxes"][0]["amount"], -15.0)

    def test_compute_all_division(self):
        tax = self._tax(10.0, amount_type="division")
        res = tax.compute_all(200.0)
        # 200 / (1 - 0.10) = 222.22
        self.assertEqual(res["total_included"], 222.22)

    def test_compute_all_group(self):
        child_a = self._tax(21.0)
        child_b = self._tax(10.0, amount_type="division")
        group = self._tax(
            0.0, amount_type="group", children_tax_ids=[(6, 0, (child_a + child_b).ids)]
        )
        res = group.compute_all(100.0)
        self.assertEqual(len(res["taxes"]), 2)
        # 21 (percent) + 11.11 (division 10% incl) = 132.11
        self.assertEqual(res["total_included"], 132.11)

    def test_compute_all_refund_matches_invoice(self):
        tax = self._tax(21.0)
        self.assertEqual(
            tax.compute_all(100.0, is_refund=True)["total_included"], 121.0
        )

    # ------------------------------------------------------------------
    # base-line pipeline
    # ------------------------------------------------------------------
    def test_pipeline_round_per_line_two_lines(self):
        tax = self._tax(21.0, price_include_override="tax_included")
        base_lines = [self._base_line(tax, 21.53) for _ in range(2)]
        Tax = self.env["account.tax"]
        for base_line in base_lines:
            Tax._add_tax_details_in_base_line(
                base_line, self.company, rounding_method="round_per_line"
            )
        Tax._round_base_lines_tax_details(base_lines, self.company)
        totals = Tax._get_tax_totals_summary(base_lines, self.currency, self.company)
        # Each line rounds independently: 17.79 + 17.79 base, 3.74 + 3.74 tax.
        # Totals are sums of per-line rounded amounts, so compare at currency
        # precision rather than by exact float identity.
        self.assertAlmostEqual(totals["base_amount"], 35.58, places=2)
        self.assertAlmostEqual(totals["tax_amount"], 7.48, places=2)
        self.assertAlmostEqual(totals["total_amount"], 43.06, places=2)

    def test_pipeline_round_globally_distributes_delta(self):
        """Round-globally spreads the rounding delta across lines (docstring case)."""
        tax = self._tax(21.0, price_include_override="tax_included")
        base_lines = [self._base_line(tax, 21.53) for _ in range(2)]
        Tax = self.env["account.tax"]
        for base_line in base_lines:
            Tax._add_tax_details_in_base_line(
                base_line, self.company, rounding_method="round_globally"
            )
        Tax._round_base_lines_tax_details(base_lines, self.company)
        totals = Tax._get_tax_totals_summary(base_lines, self.currency, self.company)
        # Globally: base 35.59, tax 7.47, total 43.06 (delta 0.01 absorbed).
        self.assertAlmostEqual(totals["base_amount"], 35.59, places=2)
        self.assertAlmostEqual(totals["tax_amount"], 7.47, places=2)
        self.assertAlmostEqual(totals["total_amount"], 43.06, places=2)
        self.assertTrue(totals["same_tax_base"])
        deltas = sorted(
            round(base_line["tax_details"]["delta_total_excluded"], 2)
            for base_line in base_lines
        )
        self.assertEqual(deltas, [0.0, 0.01])

    # ------------------------------------------------------------------
    # extra_tax_data round-trip
    # ------------------------------------------------------------------
    def test_import_extra_tax_data_keeps_manual_total_without_taxes(self):
        """A forced total-excluded on an untaxed line must survive export/import.

        '_export_base_line_extra_tax_data' stores 'manual_total_excluded' (and the
        'currency_id' sentinel) even when there are no per-tax manual amounts, e.g.
        an untaxed global-discount/down-payment delta line.  The importer must
        honour it; gating the import on 'manual_tax_amounts' would silently drop it
        (and diverge from account_tax.js, which gates on 'currency_id').
        """
        Tax = self.env["account.tax"]
        base_line = self._base_line(Tax, price_unit=100.0, manual_total_excluded=-50.0)
        extra_tax_data = Tax._export_base_line_extra_tax_data(base_line)
        self.assertNotIn("manual_tax_amounts", extra_tax_data)
        self.assertEqual(extra_tax_data.get("manual_total_excluded"), -50.0)
        imported = Tax._import_base_line_extra_tax_data(base_line, extra_tax_data)
        self.assertEqual(imported.get("manual_total_excluded"), -50.0)

    # ------------------------------------------------------------------
    # price-unit mapping
    # ------------------------------------------------------------------
    def test_adapt_price_unit_to_another_taxes(self):
        src = self._tax(6.0, price_include_override="tax_included")
        dst = self._tax(21.0, price_include_override="tax_included")
        adapted = self.env["account.tax"]._adapt_price_unit_to_another_taxes(
            106.0, None, src, dst
        )
        # 106 / 1.06 = 100 -> 100 * 1.21 = 121
        self.assertEqual(round(adapted, 4), 121.0)
