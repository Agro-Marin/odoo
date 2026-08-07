import unittest
from time import monotonic

from odoo.db.reaper import (
    _LAST_BORROW_ATTR,
    IdlePoolReaper,
    checked_out,
    note_activity,
)


class _FakePool:
    def __init__(self, size=1, available=1):
        self._size = size
        self._available = available

    def get_stats(self):
        return {"pool_size": self._size, "pool_available": self._available}


def _aged(seconds, **kwargs):
    pool = _FakePool(**kwargs)
    setattr(pool, _LAST_BORROW_ATTR, monotonic() - seconds)
    return pool


class TestCheckedOut(unittest.TestCase):
    def test_idle_pool_has_nothing_checked_out(self):
        self.assertEqual(checked_out(_FakePool(size=3, available=3)), 0)

    def test_a_held_connection_is_visible(self):
        self.assertEqual(checked_out(_FakePool(size=3, available=1)), 2)

    def test_a_pool_with_no_stats_reads_as_empty(self):
        class _Bare:
            def get_stats(self):
                return {}

        self.assertEqual(checked_out(_Bare()), 0)


class TestCollect(unittest.TestCase):
    def setUp(self):
        self.reaper = IdlePoolReaper(10.0)

    def test_a_pool_idle_past_the_ttl_is_reapable(self):
        self.assertEqual(self.reaper.collect({"a": _aged(60)}), ["a"])

    def test_a_recently_active_pool_is_spared(self):
        self.assertEqual(self.reaper.collect({"a": _aged(1)}), [])

    def test_a_pool_still_holding_a_connection_is_spared(self):
        self.assertEqual(self.reaper.collect({"a": _aged(60, available=0)}), [])

    def test_the_excluded_key_is_never_reaped(self):
        pools = {"a": _aged(60), "b": _aged(60)}
        self.assertEqual(self.reaper.collect(pools, exclude_key="a"), ["b"])

    def test_an_unstamped_pool_is_treated_as_fresh(self):
        self.assertEqual(self.reaper.collect({"a": _FakePool()}), [])

    def test_note_activity_rescues_a_stale_pool(self):
        pool = _aged(60)
        note_activity(pool)
        self.assertEqual(self.reaper.collect({"a": pool}), [])

    def test_reaping_disabled_collects_nothing(self):
        self.assertEqual(IdlePoolReaper(0).collect({"a": _aged(1e6)}), [])
        self.assertFalse(IdlePoolReaper(0).enabled)


class TestThrottle(unittest.TestCase):
    def test_interval_is_a_quarter_of_the_ttl(self):
        self.assertEqual(IdlePoolReaper(400).check_interval, 100)

    def test_interval_is_floored_at_one_second(self):
        self.assertEqual(IdlePoolReaper(0.4).check_interval, 1.0)

    def test_disabled_reaping_has_no_interval(self):
        self.assertEqual(IdlePoolReaper(0).check_interval, 0.0)

    def test_the_first_sweep_is_due(self):
        self.assertTrue(IdlePoolReaper(10).due())

    def test_a_second_sweep_is_throttled(self):
        reaper = IdlePoolReaper(10)
        self.assertTrue(reaper.due())
        self.assertFalse(reaper.due(), "two sweeps within the interval")

    def test_only_one_of_many_racing_callers_claims_the_sweep(self):
        reaper = IdlePoolReaper(10)
        self.assertEqual(sum(1 for _ in range(50) if reaper.due()), 1)

    def test_probably_due_agrees_with_due_before_any_sweep(self):
        reaper = IdlePoolReaper(10)
        self.assertTrue(reaper.probably_due())
        reaper.due()
        self.assertFalse(reaper.probably_due(), "the cheap pre-check must follow")

    def test_probably_due_does_not_consume_the_slot(self):
        reaper = IdlePoolReaper(10)
        reaper.probably_due()
        self.assertTrue(reaper.due(), "the lock-free pre-check must not stamp")

    def test_disabled_reaping_is_never_due(self):
        self.assertFalse(IdlePoolReaper(0).due())
        self.assertFalse(IdlePoolReaper(0).probably_due())


if __name__ == "__main__":
    unittest.main()
