"""``capped_backoff`` had no test at all.

It is the only backoff curve in the prefork/threaded reconnect paths
(``_threaded.py:227``, ``:237`` and ``_worker.py:319``), and its exponent bound
used to be spelled ``ceiling.bit_length()`` — correct, but derived from a
property of the ceiling unrelated to the retry count, so nothing but arithmetic
by hand said whether a rewrite preserved the curve.  This pins the curve so the
next rewrite is checked rather than reasoned about.
"""

import pytest

from odoo.service._helpers import SLEEP_INTERVAL, capped_backoff

#: ``ceiling`` -> the delay for attempts 0..11.  Doubling until the ceiling
#: clamps, then flat.
CURVES = {
    60: [1, 2, 4, 8, 16, 32, 60, 60, 60, 60, 60, 60],
    30: [1, 2, 4, 8, 16, 30, 30, 30, 30, 30, 30, 30],
    10: [1, 2, 4, 8, 10, 10, 10, 10, 10, 10, 10, 10],
    1: [1] * 12,
    0: [0] * 12,
}


@pytest.mark.parametrize("ceiling", sorted(CURVES))
def test_curve_doubles_then_clamps(ceiling):
    assert [capped_backoff(a, ceiling) for a in range(12)] == CURVES[ceiling]


def test_default_ceiling_is_the_sleep_interval():
    assert SLEEP_INTERVAL == 60
    assert [capped_backoff(a) for a in range(12)] == CURVES[60]


def test_a_runaway_attempt_count_stays_clamped_and_cheap():
    """The exponent bound exists so an unbounded ``attempts`` cannot build a
    bignum on its way to being clamped away."""
    assert capped_backoff(10_000) == SLEEP_INTERVAL
