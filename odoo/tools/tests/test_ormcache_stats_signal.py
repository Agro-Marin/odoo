"""``log_ormcache_stats`` must only claim its state machine for real signals.

The handler guards itself with a module-level ``_logger_state`` tri-state so a
second SIGUSR1 aborts an in-flight dump.  It used to move that state to "run"
*before* checking whether ``sig`` was one of the two signals it actually
dispatches on, and only the dispatch resets the state.  Any other ``sig`` --
including the ``sig=None`` default that the signature advertises for a direct
call -- therefore parked the state at "run" forever, and every subsequent
SIGUSR1 took the ``!= "wait"`` branch, set "abort" and returned.  The cache
stats dump was then dead for the remaining life of the process.
"""

import signal
import unittest

import odoo.tools.cache as cache_mod


class TestLogOrmcacheStatsSignalGating(unittest.TestCase):
    def setUp(self):
        cache_mod._logger_state = "wait"
        self.addCleanup(setattr, cache_mod, "_logger_state", "wait")

    def _drain(self):
        """Wait for the reporting thread (if any) to settle back to "wait"."""
        for thread in list(__import__("threading").enumerate()):
            if thread.name.startswith("odoo.signal.log_ormcache_stats"):
                thread.join(timeout=10)

    def test_bare_call_does_not_wedge_the_state_machine(self):
        cache_mod.log_ormcache_stats()
        self.assertEqual(
            cache_mod._logger_state,
            "wait",
            "a non-signal call must leave the state machine untouched",
        )

    def test_unrelated_signal_does_not_wedge_the_state_machine(self):
        cache_mod.log_ormcache_stats(signal.SIGTERM, None)
        self.assertEqual(cache_mod._logger_state, "wait")

    def test_dump_still_runs_after_a_bare_call(self):
        cache_mod.log_ormcache_stats()
        cache_mod.log_ormcache_stats(signal.SIGUSR1, None)
        self._drain()
        self.assertEqual(
            cache_mod._logger_state,
            "wait",
            "SIGUSR1 must still start (and finish) a dump",
        )

    def test_repeated_signals_each_run(self):
        for sig in (signal.SIGUSR1, signal.SIGUSR2, signal.SIGUSR1):
            cache_mod.log_ormcache_stats(sig, None)
            self._drain()
            self.assertEqual(cache_mod._logger_state, "wait")


if __name__ == "__main__":
    unittest.main()
