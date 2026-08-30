"""What a Profiler must leave behind: nothing.

Both defects here were invisible to the suite because nothing asserted the
*process* state after a profile -- only the entries it produced.
"""

import sys
import unittest

from odoo.tools.profiler import Collector, MemoryCollector, Profiler, SyncCollector
from odoo.tools.profiler import _lock as _memory_collector_lock


class _Exploding(Collector):
    name = "exploding_test_collector"

    def stop(self):
        msg = "boom"
        raise RuntimeError(msg)


class TestSyncCollectorUninstallsItsTrace(unittest.TestCase):
    def setUp(self):
        self.addCleanup(sys.settrace, None)
        sys.settrace(None)

    def test_a_clean_profile_leaves_no_trace_function(self):
        # `sys.gettrace() is self.hook` compared against a bound method built
        # fresh on every attribute access, so it was never true and the hook was
        # never removed -- on the ordinary path, no exception involved.
        with Profiler(db=None, collectors=[SyncCollector()], description="t"):
            pass
        self.assertIsNone(sys.gettrace())

    def test_the_hook_identity_is_stable(self):
        collector = SyncCollector()
        self.assertIs(collector._hook, collector._hook)
        self.assertIsNot(collector.hook, collector.hook)

    def test_sync_profiling_works_more_than_once_per_thread(self):
        # start() refuses when a trace function is already installed. A leaked
        # hook tripped that guard permanently.
        for _ in range(3):
            with Profiler(db=None, collectors=[SyncCollector()], description="t"):
                pass
        self.assertIsNone(sys.gettrace())


class TestEndStopsEveryCollector(unittest.TestCase):
    def setUp(self):
        self.addCleanup(sys.settrace, None)
        sys.settrace(None)

    def test_a_raising_collector_does_not_strand_the_others(self):
        profiler = Profiler(
            db=None, collectors=[_Exploding(), SyncCollector()], description="t"
        )
        with self.assertLogs("odoo.tools.profiler", "ERROR"), profiler:
            pass
        self.assertIsNone(sys.gettrace(), "SyncCollector never got its stop()")

    def test_a_raising_collector_does_not_strand_the_memory_lock(self):
        import tracemalloc

        profiler = Profiler(
            db=None, collectors=[_Exploding(), MemoryCollector()], description="t"
        )
        with self.assertLogs("odoo.tools.profiler", "ERROR"), profiler:
            pass
        self.addCleanup(tracemalloc.stop)
        acquired = _memory_collector_lock.acquire(timeout=0.5)
        if acquired:
            _memory_collector_lock.release()
        self.assertTrue(
            acquired,
            "the process-wide memory-collector lock was never released, so no "
            "later MemoryCollector in this process can start",
        )
        self.assertFalse(tracemalloc.is_tracing())


if __name__ == "__main__":
    unittest.main()
