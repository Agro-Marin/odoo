from odoo.tests import tagged

from .common import BaseTaxCommon


@tagged("post_install", "-at_install")
class TestGlobalDiscount(BaseTaxCommon):
    """F012: `_prepare_global_discount_lines`/`_dispatch_global_discount_lines`/
    `_squash_global_discount_lines` had zero coverage in this suite (they are
    exercised indirectly by `account`/`sale`'s own test suites, but nothing
    here would catch a regression when auditing base_tax in isolation)."""

    def test_percent_discount_reduces_totals(self):
        tax = self._tax(21.0)
        Tax = self.env["account.tax"]
        base_lines = [self._base_line(tax, 100.0), self._base_line(tax, 50.0)]
        Tax._add_tax_details_in_base_lines(base_lines, self.company)
        Tax._round_base_lines_tax_details(base_lines, self.company)

        discount_lines = Tax._prepare_global_discount_lines(
            base_lines=base_lines,
            company=self.company,
            amount_type="percent",
            amount=10.0,
        )
        all_lines = base_lines + discount_lines
        Tax._add_tax_details_in_base_lines(all_lines, self.company)
        Tax._round_base_lines_tax_details(all_lines, self.company)
        totals = Tax._get_tax_totals_summary(all_lines, self.currency, self.company)

        self.assertAlmostEqual(totals["base_amount"], 135.0, places=2)
        self.assertAlmostEqual(totals["tax_amount"], 28.35, places=2)

    def test_percent_discount_over_100_does_not_crash(self):
        """Edge case: a discount larger than the discountable base must not
        raise — it should simply overshoot into negative totals."""
        tax = self._tax(21.0)
        Tax = self.env["account.tax"]
        base_lines = [self._base_line(tax, 100.0)]
        Tax._add_tax_details_in_base_lines(base_lines, self.company)
        Tax._round_base_lines_tax_details(base_lines, self.company)

        discount_lines = Tax._prepare_global_discount_lines(
            base_lines=base_lines,
            company=self.company,
            amount_type="percent",
            amount=150.0,
        )
        all_lines = base_lines + discount_lines
        Tax._add_tax_details_in_base_lines(all_lines, self.company)
        Tax._round_base_lines_tax_details(all_lines, self.company)
        totals = Tax._get_tax_totals_summary(all_lines, self.currency, self.company)

        self.assertAlmostEqual(totals["base_amount"], -50.0, places=2)


@tagged("post_install", "-at_install")
class TestDownPayment(BaseTaxCommon):
    """F012: `_prepare_down_payment_lines`/`_prepare_base_lines_for_down_payment`
    had zero coverage in this suite."""

    def test_percent_down_payment_happy_path(self):
        tax = self._tax(21.0)
        Tax = self.env["account.tax"]
        base_lines = [self._base_line(tax, 100.0), self._base_line(tax, 200.0)]
        Tax._add_tax_details_in_base_lines(base_lines, self.company)
        Tax._round_base_lines_tax_details(base_lines, self.company)

        dp_lines = Tax._prepare_down_payment_lines(
            base_lines=base_lines,
            company=self.company,
            amount_type="percent",
            amount=30.0,
        )
        Tax._add_tax_details_in_base_lines(dp_lines, self.company)
        Tax._round_base_lines_tax_details(dp_lines, self.company)
        totals = Tax._get_tax_totals_summary(dp_lines, self.currency, self.company)

        self.assertAlmostEqual(totals["base_amount"], 90.0, places=2)
        self.assertAlmostEqual(totals["tax_amount"], 18.9, places=2)

    def test_fixed_down_payment_exceeding_order_total(self):
        """Edge case: a fixed down payment larger than the order's own total
        must not raise — `amount` ("fixed") targets the tax-included total."""
        tax = self._tax(21.0)
        Tax = self.env["account.tax"]
        base_lines = [self._base_line(tax, 100.0)]
        Tax._add_tax_details_in_base_lines(base_lines, self.company)
        Tax._round_base_lines_tax_details(base_lines, self.company)

        dp_lines = Tax._prepare_down_payment_lines(
            base_lines=base_lines,
            company=self.company,
            amount_type="fixed",
            amount=500.0,
        )
        Tax._add_tax_details_in_base_lines(dp_lines, self.company)
        Tax._round_base_lines_tax_details(dp_lines, self.company)
        totals = Tax._get_tax_totals_summary(dp_lines, self.currency, self.company)

        self.assertAlmostEqual(totals["total_amount"], 500.0, places=2)


@tagged("post_install", "-at_install")
class TestReturnOfMerchandise(BaseTaxCommon):
    """F012: the return-of-merchandise matching/dispatch/squash trio
    (`_dispatch_return_of_merchandise_lines`, `_match_returns_to_positive_lines`,
    `_squash_return_of_merchandise_lines`) had zero coverage in this suite."""

    def _product(self, name):
        return self.env["product.product"].create({"name": name})

    def test_return_matches_into_the_positive_line(self):
        tax = self._tax(21.0)
        Tax = self.env["account.tax"]
        product = self._product("BT return test product")

        positive = self._base_line(tax, 10.0, quantity=5.0, product_id=product)
        negative = self._base_line(tax, 10.0, quantity=-2.0, product_id=product)
        Tax._add_tax_details_in_base_lines([positive, negative], self.company)
        Tax._round_base_lines_tax_details([positive, negative], self.company)

        new_base_lines = Tax._dispatch_return_of_merchandise_lines(
            [positive, negative], self.company
        )
        # The negative line was fully matched and dispatched into the
        # positive line's `return_of_merchandise_base_lines`, so it is
        # excluded from the result — only the positive line's copy remains.
        self.assertEqual(len(new_base_lines), 1)
        self.assertTrue(new_base_lines[0]["return_of_merchandise_base_lines"])

        Tax._squash_return_of_merchandise_lines(new_base_lines, self.company)
        self.assertAlmostEqual(new_base_lines[0]["quantity"], 3.0)

    def test_over_return_creates_a_standalone_line(self):
        """Edge case: a return quantity exceeding all available positive
        quantity must not be silently dropped — the unmatched remainder
        becomes its own new base line (`plus_base_line: None` branch)."""
        tax = self._tax(21.0)
        Tax = self.env["account.tax"]
        product = self._product("BT over-return test product")

        positive = self._base_line(tax, 10.0, quantity=3.0, product_id=product)
        negative = self._base_line(tax, 10.0, quantity=-5.0, product_id=product)
        Tax._add_tax_details_in_base_lines([positive, negative], self.company)
        Tax._round_base_lines_tax_details([positive, negative], self.company)

        new_base_lines = Tax._dispatch_return_of_merchandise_lines(
            [positive, negative], self.company
        )
        # positive line's copy (absorbed 3 units) + a new standalone line for
        # the 2 units of return that exceeded all available positive stock.
        self.assertEqual(len(new_base_lines), 2)
        standalone = [
            bl for bl in new_base_lines if not bl["return_of_merchandise_base_lines"]
        ]
        self.assertEqual(len(standalone), 1)
        self.assertAlmostEqual(standalone[0]["quantity"], -2.0)


@tagged("post_install", "-at_install")
class TestGrossTotalTolerance(BaseTaxCommon):
    """F012: the ~450-line gross-total tolerance/rounding family
    (`_round_raw_total_excluded` and friends) had zero direct coverage in this
    suite — only exercised implicitly through the plain rounding pipeline."""

    def test_strict_tolerance_keeps_the_group_total_exact(self):
        tax = self._tax(21.0)
        Tax = self.env["account.tax"]
        base_lines = [self._base_line(tax, 10.01), self._base_line(tax, 10.02)]
        Tax._add_tax_details_in_base_lines(base_lines, self.company)
        Tax._round_base_lines_tax_details(base_lines, self.company)

        expected_total = sum(
            bl["tax_details"]["raw_total_excluded_currency"] for bl in base_lines
        )
        # Perturb one line's raw total by a sub-cent amount, as float drift
        # from an earlier computation step would.
        base_lines[0]["tax_details"]["raw_total_excluded_currency"] += 0.0004

        Tax._round_raw_total_excluded(
            base_lines,
            self.company,
            precision_digits=2,
            apply_strict_tolerance=True,
        )
        rounded_sum = sum(
            bl["tax_details"]["raw_total_excluded_currency"] for bl in base_lines
        )
        self.assertAlmostEqual(rounded_sum, round(expected_total, 2), places=2)

    def test_strict_tolerance_with_a_single_line_is_a_no_op(self):
        """Edge case: nothing to redistribute across when there is only one
        line in the group — must not raise."""
        tax = self._tax(21.0)
        Tax = self.env["account.tax"]
        base_lines = [self._base_line(tax, 10.005)]
        Tax._add_tax_details_in_base_lines(base_lines, self.company)
        Tax._round_base_lines_tax_details(base_lines, self.company)

        Tax._round_raw_total_excluded(
            base_lines,
            self.company,
            precision_digits=2,
            apply_strict_tolerance=True,
        )
        self.assertAlmostEqual(
            base_lines[0]["tax_details"]["raw_total_excluded_currency"],
            10.0 if round(10.005, 2) == 10.0 else 10.01,
            places=2,
        )
