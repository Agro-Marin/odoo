import random

import pytest

from odoo.libs import backoff


class TestBound:
    def test_first_attempt_is_the_base(self):
        assert backoff.bound(1, base=0.2, cap=2.0) == 0.2

    def test_the_ceiling_doubles_until_it_reaches_the_cap(self):
        assert list(backoff.bounds(5, base=0.2, cap=2.0)) == [0.2, 0.4, 0.8, 1.6, 2.0]

    def test_the_schedule_grows_strictly_until_capped(self):
        # The assertion whose absence let a flat "exponential" backoff ship twice.
        # A cap that swallows the growth term makes every retry draw from the
        # same interval; that is invisible to any test that looks at one delay.
        seen = list(backoff.bounds(6, base=0.2, cap=2.0))
        growing = [b for b in seen if b < 2.0]
        assert growing == sorted(set(growing)), f"schedule is not strictly growing: {seen}"
        assert len(growing) >= 3, f"cap swallowed the curve after {len(growing)} attempt(s): {seen}"

    def test_the_cap_is_never_exceeded(self):
        assert all(b <= 2.0 for b in backoff.bounds(20, base=0.2, cap=2.0))

    def test_a_cap_below_the_base_is_rejected_rather_than_flattening_the_curve(self):
        # This is the misconfiguration that shipped: the growth term reached the
        # cap on attempt 1, so the cap won every time and the curve was flat.
        with pytest.raises(ValueError, match="flattens the curve"):
            backoff.bound(1, base=2.0, cap=1.5)

    @pytest.mark.parametrize("attempt", [0, -1])
    def test_attempt_is_one_based(self, attempt):
        with pytest.raises(ValueError, match="1-based"):
            backoff.bound(attempt, base=0.2, cap=2.0)

    def test_a_non_positive_base_is_rejected(self):
        with pytest.raises(ValueError, match="base must be positive"):
            backoff.bound(1, base=0.0, cap=2.0)


class TestDelay:
    def test_delay_stays_within_the_bound_for_every_attempt(self):
        rng = random.Random(20260808)
        for attempt in range(1, 6):
            ceiling = backoff.bound(attempt, base=0.2, cap=2.0)
            for _ in range(200):
                assert 0.0 <= backoff.delay(attempt, base=0.2, cap=2.0, rng=rng) <= ceiling

    def test_later_attempts_wait_longer_on_average(self):
        # The property that matters under contention: the distribution must
        # actually move, not just the code that computes it.
        rng = random.Random(20260808)
        means = [
            sum(backoff.delay(a, base=0.2, cap=2.0, rng=rng) for _ in range(2000)) / 2000
            for a in (1, 2, 3, 4)
        ]
        assert means == sorted(means), f"mean wait does not increase per attempt: {means}"
        assert means[-1] > means[0] * 4, f"growth is far below the doubling curve: {means}"

    def test_the_rng_is_injectable_and_deterministic(self):
        a = [backoff.delay(2, base=0.2, cap=2.0, rng=random.Random(7)) for _ in range(3)]
        b = [backoff.delay(2, base=0.2, cap=2.0, rng=random.Random(7)) for _ in range(3)]
        assert a == b


class TestCallSitesAreNotFlat:
    """The two loops that shipped the flat curve, pinned at their own constants."""

    def test_retrying_schedule_grows(self):
        from odoo.service.transaction import (
            BASE_CONCURRENCY_BACKOFF_SECONDS,
            MAX_CONCURRENCY_BACKOFF_SECONDS,
            MAX_TRIES_ON_CONCURRENCY_FAILURE,
        )

        seen = list(
            backoff.bounds(
                MAX_TRIES_ON_CONCURRENCY_FAILURE,
                base=BASE_CONCURRENCY_BACKOFF_SECONDS,
                cap=MAX_CONCURRENCY_BACKOFF_SECONDS,
            )
        )
        assert len(set(seen)) > 1, f"retrying() backoff is flat: {seen}"
        assert seen[0] < seen[-1]

    def test_ir_job_concurrency_schedule_grows(self):
        # ir_job cannot be imported without an addons path, so read its constants
        # from source. Hardcoding them here would pin nothing.
        import pathlib
        import re

        source = (
            pathlib.Path(__file__).resolve().parents[2]
            / "addons"
            / "base"
            / "models"
            / "ir_job.py"
        ).read_text()

        def constant(name: str) -> float:
            match = re.search(rf"^{name} = ([0-9.]+)$", source, re.MULTILINE)
            assert match, f"{name} not found in ir_job.py"
            return float(match[1])

        seen = list(
            backoff.bounds(
                int(constant("CONCURRENCY_MAX_ATTEMPTS")),
                base=constant("CONCURRENCY_BACKOFF_BASE_S"),
                cap=constant("CONCURRENCY_BACKOFF_MAX_S"),
            )
        )
        assert len(set(seen)) > 1, f"ir_job concurrency backoff is flat: {seen}"
        assert seen[0] < seen[-1]
