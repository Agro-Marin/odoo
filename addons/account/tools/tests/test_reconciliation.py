from addons.account.tools.reconciliation import (
    _partial_amounts_across_rates,
    _ranges_overlap,
    amount_range_after_rate,
    pick_reconciliation_currency,
)


class Rounding:
    def __init__(self, rounding, name="cur"):
        self.rounding = rounding
        self.name = name

    def round(self, amount):
        quotient = amount / self.rounding
        floored = int(quotient)
        remainder = abs(quotient - floored)
        if remainder >= 0.5:
            floored += 1 if quotient >= 0 else -1
        return floored * self.rounding

    def compare_amounts(self, amount1, amount2):
        diff = self.round(amount1 - amount2)
        if diff > 0:
            return 1
        if diff < 0:
            return -1
        return 0

    def __repr__(self):
        return f"<{self.name}>"


CENTS = Rounding(0.01, "EUR")
UNITS = Rounding(1.0, "JPY")


def test_zero_rate_yields_a_zero_band():
    assert amount_range_after_rate(CENTS, CENTS, 1000.0, 0) == (0.0, 0.0, 0.0)
    assert amount_range_after_rate(CENTS, CENTS, 1000.0, None) == (0.0, 0.0, 0.0)


def test_band_brackets_the_midpoint():
    low, mid, high = amount_range_after_rate(CENTS, CENTS, 1000.0, 12.0)
    assert low < mid < high, (low, mid, high)
    assert mid == 12000.0
    assert round(mid - low, 2) == 0.06
    assert round(high - mid, 2) == 0.06


def test_band_is_a_point_when_the_step_is_negligible_against_the_rate():
    low, mid, high = amount_range_after_rate(CENTS, CENTS, 100.0, 0.0001)
    assert low == mid == high


def test_band_uses_the_source_step_and_the_target_rounding():
    low, mid, high = amount_range_after_rate(UNITS, CENTS, 100.0, 2.0)
    assert (low, mid, high) == (199.0, 200.0, 201.0)


def test_band_handles_a_negative_amount():
    low, mid, high = amount_range_after_rate(CENTS, CENTS, -1000.0, 12.0)
    assert low < mid < high
    assert mid == -12000.0


COMPANY = Rounding(0.01, "COMPANY")
FOREIGN_A = Rounding(0.01, "FOREIGN_A")
FOREIGN_B = Rounding(0.01, "FOREIGN_B")


def test_falls_back_to_company_currency_when_both_sides_are_domestic():
    assert (
        pick_reconciliation_currency(
            COMPANY, COMPANY, COMPANY, {COMPANY: 1}, {COMPANY: 1}
        )
        is COMPANY
    )


def test_needs_a_residual_on_both_sides_to_use_a_foreign_currency():
    assert (
        pick_reconciliation_currency(
            FOREIGN_A, COMPANY, COMPANY, {FOREIGN_A: 1}, {COMPANY: 1}
        )
        is COMPANY
    )


def test_uses_the_foreign_currency_when_both_sides_have_a_residual_in_it():
    assert (
        pick_reconciliation_currency(
            FOREIGN_A, COMPANY, COMPANY, {FOREIGN_A: 1}, {FOREIGN_A: 1, COMPANY: 1}
        )
        is FOREIGN_A
    )


def test_credit_currency_is_used_when_only_it_qualifies():
    assert (
        pick_reconciliation_currency(
            COMPANY, FOREIGN_B, COMPANY, {FOREIGN_B: 1}, {FOREIGN_B: 1}
        )
        is FOREIGN_B
    )


def test_debit_wins_when_both_foreign_currencies_qualify():
    both = {FOREIGN_A: 1, FOREIGN_B: 1}
    assert pick_reconciliation_currency(FOREIGN_A, FOREIGN_B, COMPANY, both, both) is (
        FOREIGN_A
    )
    assert pick_reconciliation_currency(FOREIGN_B, FOREIGN_A, COMPANY, both, both) is (
        FOREIGN_B
    )


def test_ranges_overlap_when_each_amount_sits_inside_the_other_range():
    debit_range = (10.00, 10.02, 10.04)
    credit_range = (10.01, 10.03, 10.05)
    assert _ranges_overlap(CENTS, 10.02, 10.03, debit_range, credit_range)


def test_ranges_do_not_overlap_when_an_amount_falls_outside_the_other_range():
    debit_range = (10.00, 10.02, 10.04)
    credit_range = (10.01, 10.03, 10.05)
    assert not _ranges_overlap(CENTS, 9.00, 10.03, debit_range, credit_range)


def test_across_rates_settles_each_side_within_its_own_band_when_bands_dont_overlap():
    context = {
        "company_currency": CENTS,
        "debit_currency": UNITS,
        "credit_currency": UNITS,
        "min_recon_amount": 100.0,
        "debit_recon_values": {"rate": 0.5},
        "credit_recon_values": {"rate": 0.4},
        "remaining_debit_amount": 300.0,
        "remaining_credit_amount": -300.0,
    }
    # debit_range = amount_range_after_rate(UNITS, CENTS, 100.0, 1/0.5) = (199.0, 200.0, 201.0)
    # credit_range = amount_range_after_rate(UNITS, CENTS, 100.0, 1/0.4) = (248.75, 250.0, 251.25)
    # Neither band contains the other's midpoint, so the ranges don't overlap and
    # each side settles at its own converted amount rather than the full residual.
    assert _partial_amounts_across_rates(context) == {
        "partial_amount": 200.0,
        "partial_debit_amount_currency": 100.0,
        "partial_credit_amount_currency": 100.0,
        "partial_debit_amount": 200.0,
        "partial_credit_amount": 250.0,
    }


def test_across_rates_collapses_to_the_full_residual_when_bands_overlap():
    context = {
        "company_currency": CENTS,
        "debit_currency": UNITS,
        "credit_currency": UNITS,
        "min_recon_amount": 100.0,
        "debit_recon_values": {"rate": 0.5},
        "credit_recon_values": {"rate": 0.5},
        "remaining_debit_amount": 300.0,
        "remaining_credit_amount": -300.0,
    }
    # Both sides convert to the identical (199.0, 200.0, 201.0) band, so each
    # amount necessarily falls inside the other's band: settle the whole
    # residual instead of leaving a rounding-window cent behind.
    assert _partial_amounts_across_rates(context) == {
        "partial_amount": 300.0,
        "partial_debit_amount_currency": 100.0,
        "partial_credit_amount_currency": 100.0,
        "partial_debit_amount": 300.0,
        "partial_credit_amount": 300.0,
    }
