"""Tier-1 (database-free) tests for :mod:`odoo.db.breaker`.

The schedule is the whole point, so it is pinned here rather than inferred from
a live replica: a blip must recover in about a second where the flat 20-minute
window it replaces would have cost 20 minutes of primary load, and a genuinely
dead endpoint must settle at a ceiling no worse than that old window.  Only one
caller may probe at a time, or a dead replica draws a connection attempt from
every request that arrives while it is out.
"""

import unittest

from odoo.db.breaker import CircuitBreaker


class TestClosedBreaker(unittest.TestCase):
    def test_a_fresh_breaker_allows_everything(self):
        breaker = CircuitBreaker(max_cooldown=1200)
        self.assertTrue(breaker.closed)
        self.assertTrue(all(breaker.allow() for _ in range(10)))

    def test_success_on_a_closed_breaker_changes_nothing(self):
        breaker = CircuitBreaker(max_cooldown=1200)
        breaker.record_success()
        self.assertTrue(breaker.closed)
        self.assertEqual(breaker.cooldown_remaining, 0.0)


class TestOpening(unittest.TestCase):
    def setUp(self):
        self.breaker = CircuitBreaker(max_cooldown=1200, initial_cooldown=60)

    def test_one_failure_opens_it(self):
        self.breaker.record_failure()
        self.assertFalse(self.breaker.closed)
        self.assertFalse(self.breaker.allow())

    def test_the_first_window_is_the_initial_cooldown(self):
        self.breaker.record_failure()
        self.assertAlmostEqual(self.breaker.cooldown_remaining, 60, delta=1)

    def _fail_a_probe(self, breaker):
        """Drive one genuine probe *cycle*: let the window elapse, claim the
        probe, and report it failed — the only thing that widens the window."""
        breaker._opened_at -= breaker._cooldown + 1
        assert breaker.allow(), "probe should be admitted once the window elapsed"
        breaker.record_failure()

    def test_repeated_probe_cycles_double_the_window(self):
        # The window doubles once per *probe cycle*, not once per failure. The
        # first failure trips it; each subsequent widening needs a probe to be
        # admitted and to fail again.
        widths = [round(self.breaker.cooldown_remaining)]
        self.breaker.record_failure()
        widths.append(round(self.breaker.cooldown_remaining))
        for _ in range(4):
            self._fail_a_probe(self.breaker)
            widths.append(round(self.breaker.cooldown_remaining))
        self.assertEqual(widths, [0, 60, 120, 240, 480, 960])

    def test_the_window_is_capped(self):
        self.breaker.record_failure()
        for _ in range(20):
            self._fail_a_probe(self.breaker)
        self.assertLessEqual(self.breaker.cooldown_remaining, 1200)

    def test_the_cap_is_never_worse_than_the_flat_window_it_replaced(self):
        breaker = CircuitBreaker(max_cooldown=20 * 60)
        breaker.record_failure()
        for _ in range(50):
            self._fail_a_probe(breaker)
        self.assertLessEqual(breaker.cooldown_remaining, 20 * 60)

    def test_a_burst_of_concurrent_failures_opens_only_the_initial_window(self):
        """A single blip with N in-flight requests must not widen N times.

        Every request that passed ``allow()`` while the breaker was closed is
        already talking to the replica when it goes down; each fails and lands
        in ``record_failure``. Only the first trips the breaker; the rest are
        stragglers against no outstanding probe and must leave the window at the
        initial cooldown — the pile-on that used to turn a 2-second outage into
        a 20-minute one.
        """
        for _ in range(12):  # 12 concurrent failures from one blip
            self.breaker.record_failure()
        self.assertEqual(self.breaker.trips, 1)
        self.assertEqual(self.breaker.failures, 12)
        self.assertAlmostEqual(self.breaker.cooldown_remaining, 60, delta=1)

    def test_trips_counts_open_transitions_not_failures(self):
        for _ in range(4):
            self.breaker.record_failure()
        self.assertEqual(self.breaker.trips, 1)
        self.assertEqual(self.breaker.failures, 4)


class TestProbing(unittest.TestCase):
    def setUp(self):
        self.breaker = CircuitBreaker(max_cooldown=1200, initial_cooldown=0.0)

    def test_the_window_elapsing_admits_a_probe(self):
        self.breaker.record_failure()
        self.assertTrue(self.breaker.allow())

    def test_only_one_caller_probes(self):
        """Otherwise every request arriving while the replica is out attempts
        its own connection to a host already known to be failing."""
        self.breaker.record_failure()
        self.assertEqual(sum(1 for _ in range(50) if self.breaker.allow()), 1)

    def test_a_successful_probe_closes_and_resets_the_backoff(self):
        for _ in range(3):
            self.breaker.record_failure()
        self.assertTrue(self.breaker.allow())
        self.breaker.record_success()
        self.assertTrue(self.breaker.closed)
        self.breaker.record_failure()
        self.assertEqual(self.breaker.failures, 1, "the backoff must start over")

    def test_a_failed_probe_widens_the_window_again(self):
        breaker = CircuitBreaker(max_cooldown=1200, initial_cooldown=60)
        breaker.record_failure()
        first = breaker.cooldown_remaining
        breaker._opened_at -= 61
        self.assertTrue(breaker.allow())
        breaker.record_failure()
        self.assertGreater(breaker.cooldown_remaining, first)

    def test_an_abandoned_probe_does_not_wedge_the_breaker(self):
        """A caller that raises without reporting back would otherwise leave the
        breaker half-open forever, silently disabling the endpoint."""
        breaker = CircuitBreaker(max_cooldown=1200, initial_cooldown=60)
        breaker.record_failure()
        breaker._opened_at -= 61
        self.assertTrue(breaker.allow(), "first probe claimed")
        self.assertFalse(breaker.allow(), "second blocked while the probe runs")
        breaker._probing_since -= 61
        self.assertTrue(breaker.allow(), "an abandoned probe must be reclaimable")


class TestConcurrentPileOn(unittest.TestCase):
    """The pile-on reproduced with real threads, GIL-masked races and all.

    ``test_a_burst_...`` drives the failures sequentially; this fires them from
    N threads at once against the actual ``threading.Lock``, which is how the
    bug manifests in production (every in-flight readonly request reporting its
    own failure through ``Registry.cursor``).
    """

    def test_a_thundering_herd_of_failures_still_opens_one_short_window(self):
        import threading

        breaker = CircuitBreaker(max_cooldown=1200, initial_cooldown=60)
        barrier = threading.Barrier(24)

        def fail():
            barrier.wait()
            breaker.record_failure()

        threads = [threading.Thread(target=fail) for _ in range(24)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(breaker.trips, 1, "exactly one closed→open transition")
        self.assertEqual(breaker.failures, 24)
        # Before the fix this was 60 * 2**23, clamped to 1200 — the 20-minute
        # window a single blip must never produce.
        self.assertAlmostEqual(breaker.cooldown_remaining, 60, delta=2)


class TestSnapshot(unittest.TestCase):
    def test_a_healthy_breaker_reports_closed(self):
        snap = CircuitBreaker(max_cooldown=1200).snapshot()
        self.assertTrue(snap["closed"])
        self.assertEqual(snap["failures"], 0)
        self.assertEqual(snap["cooldown_seconds"], 0.0)

    def test_an_open_breaker_reports_its_window(self):
        breaker = CircuitBreaker(max_cooldown=1200, initial_cooldown=60)
        breaker.record_failure()
        snap = breaker.snapshot()
        self.assertFalse(snap["closed"])
        self.assertEqual(snap["failures"], 1)
        self.assertEqual(snap["trips"], 1)
        self.assertEqual(snap["cooldown_seconds"], 60.0)


class TestConstruction(unittest.TestCase):
    def test_a_ceiling_below_the_first_step_is_rejected(self):
        with self.assertRaises(ValueError):
            CircuitBreaker(max_cooldown=0.5, initial_cooldown=1.0)


if __name__ == "__main__":
    unittest.main()
