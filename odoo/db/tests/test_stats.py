import unittest
from time import monotonic

from odoo.db.budget import ConnectionBudget
from odoo.db.stats import _WAIT_BUCKETS, PoolStats


class TestBorrowWaitHistogram(unittest.TestCase):
    def setUp(self):
        self.stats = PoolStats()

    def _record(self, waited):
        self.stats.record_borrow(monotonic() - waited)

    def test_a_fast_borrow_lands_in_the_first_bucket(self):
        self._record(0.0)
        snap = self.stats.snapshot()
        self.assertEqual(snap["borrows"], 1)
        self.assertEqual(snap["borrow_wait_seconds"][f"le_{_WAIT_BUCKETS[0]}"], 1)

    def test_buckets_are_cumulative(self):
        for waited in (0.0, 0.05, 2.0):
            self._record(waited)
        waits = self.stats.snapshot()["borrow_wait_seconds"]
        counts = list(waits.values())
        self.assertEqual(counts, sorted(counts), "a cumulative histogram cannot dip")
        self.assertEqual(waits["le_+Inf"], 3, "every borrow must be in the last bucket")

    def test_a_borrow_slower_than_every_edge_only_reaches_inf(self):
        self._record(_WAIT_BUCKETS[-1] + 1)
        waits = self.stats.snapshot()["borrow_wait_seconds"]
        self.assertEqual(waits[f"le_{_WAIT_BUCKETS[-1]}"], 0)
        self.assertEqual(waits["le_+Inf"], 1)

    def test_max_tracks_the_slowest_borrow(self):
        for waited in (0.0, 0.4, 0.1):
            self._record(waited)
        self.assertGreaterEqual(self.stats.snapshot()["borrow_wait_seconds_max"], 0.4)

    def test_totals_are_monotonic_across_snapshots(self):
        self._record(0.0)
        first = self.stats.snapshot()["borrows"]
        self._record(0.0)
        self.assertGreater(self.stats.snapshot()["borrows"], first)


class TestSnapshotShape(unittest.TestCase):
    def test_gauges_are_omitted_without_a_budget(self):
        snap = PoolStats().snapshot()
        self.assertNotIn("budget_maxconn", snap)

    def test_budget_gauges_are_reported_when_given_one(self):
        budget = ConnectionBudget(4)
        snap = PoolStats().snapshot(budget=budget, direct_out=2, pools=3)
        self.assertEqual(snap["budget_maxconn"], 4)
        self.assertEqual(snap["budget_available"], 4)
        self.assertEqual(snap["budget_in_use"], 0)
        self.assertEqual(snap["direct_out"], 2)
        self.assertEqual(snap["pools"], 3)

    def test_every_counter_starts_at_zero(self):
        snap = PoolStats().snapshot()
        numeric = {k: v for k, v in snap.items() if isinstance(v, (int, float))}
        self.assertTrue(numeric)
        self.assertEqual(set(numeric.values()), {0})


class TestBudgetAccounting(unittest.TestCase):
    def test_in_use_and_available_are_complementary(self):
        budget = ConnectionBudget(3)
        self.assertTrue(budget.acquire(0))
        self.assertEqual(budget.in_use, 1)
        self.assertEqual(budget.available, 2)
        budget.release()
        self.assertEqual(budget.in_use, 0)

    def test_exhaustion_is_counted_on_the_budget_not_the_pool(self):
        budget = ConnectionBudget(1)
        self.assertTrue(budget.acquire(0))
        self.assertFalse(budget.acquire(0))
        self.assertFalse(budget.acquire(0))
        self.assertEqual(budget.exhausted, 2, "saturation must be visible as a count")
        budget.release()

    def test_a_successful_acquire_does_not_count_as_exhaustion(self):
        budget = ConnectionBudget(1)
        self.assertTrue(budget.acquire(0))
        self.assertEqual(budget.exhausted, 0)
        budget.release()

    def test_a_shared_budget_reports_one_total_for_both_pools(self):
        budget = ConnectionBudget(1)
        self.assertTrue(budget.acquire(0))
        budget.acquire(0)
        left = PoolStats().snapshot(budget=budget)
        right = PoolStats().snapshot(budget=budget)
        self.assertEqual(left["budget_exhausted"], right["budget_exhausted"], 1)
        budget.release()

    def test_a_double_release_is_loud(self):
        budget = ConnectionBudget(1)
        self.assertTrue(budget.acquire(0))
        budget.release()
        with self.assertRaises(ValueError):
            budget.release()

    def test_maxconn_must_be_positive(self):
        with self.assertRaises(ValueError):
            ConnectionBudget(0)


if __name__ == "__main__":
    unittest.main()
