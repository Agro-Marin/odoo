"""Tier-1 (database-free) tests for :mod:`odoo.db.lag`.

Two things have to hold or the ceiling is worse than not having one.

It must not demote a *healthy* replica. ``pg_last_xact_replay_timestamp()``
grows without bound on an idle primary — measured 43s against a standby with
nothing left to apply — so a naive ``now() - last_replay`` sends reads back to
the primary precisely when the system is quiet. :data:`~odoo.db.lag.LAG_SQL`
reports zero when the standby has replayed everything it received, and the shape
of that SQL is pinned here because it is the whole correctness argument.

And it must not demote on a *failed measurement*: a replica that cannot answer
the lag query is one whose failure the breaker sees, and refusing reads because
the question failed would demote on no evidence.
"""

import unittest

from odoo.db.lag import LAG_SQL, ReplicaLagGate


class TestDisabled(unittest.TestCase):
    def setUp(self):
        self.gate = ReplicaLagGate(0.0)

    def test_a_zero_ceiling_is_disabled(self):
        self.assertFalse(self.gate.enabled)

    def test_it_allows_everything(self):
        self.assertTrue(self.gate.allows())

    def test_it_never_asks_for_a_sample(self):
        """So the lag query is never issued at all when the feature is off."""
        self.assertFalse(self.gate.due_for_sample())

    def test_even_a_huge_recorded_lag_allows(self):
        self.gate.record(9999.0)
        self.assertTrue(self.gate.allows())

    def test_a_negative_ceiling_is_rejected(self):
        with self.assertRaises(ValueError):
            ReplicaLagGate(-1.0)


class TestVerdict(unittest.TestCase):
    def setUp(self):
        self.gate = ReplicaLagGate(30.0)

    def test_a_fresh_gate_allows(self):
        self.assertTrue(self.gate.allows())

    def test_lag_under_the_ceiling_allows(self):
        self.gate.record(5.0)
        self.assertTrue(self.gate.allows())

    def test_lag_over_the_ceiling_demotes(self):
        self.gate.record(45.0)
        self.assertFalse(self.gate.allows())

    def test_exactly_the_ceiling_still_allows(self):
        self.gate.record(30.0)
        self.assertTrue(self.gate.allows())

    def test_recovery_reopens_the_gate(self):
        self.gate.record(45.0)
        self.gate.record(1.0)
        self.assertTrue(self.gate.allows())

    def test_an_unmeasurable_lag_is_treated_as_healthy(self):
        self.gate.record(45.0)
        self.gate.record(None)
        self.assertTrue(self.gate.allows())
        self.assertEqual(self.gate.last_lag, 0.0)

    def test_a_negative_measurement_is_clamped(self):
        """Clock skew between ``now()`` and the replay timestamp can go negative."""
        self.gate.record(-3.0)
        self.assertEqual(self.gate.last_lag, 0.0)
        self.assertTrue(self.gate.allows())


class TestSampling(unittest.TestCase):
    def test_the_interval_defaults_to_a_quarter_of_the_ceiling(self):
        self.assertEqual(ReplicaLagGate(120.0).sample_interval, 30.0)

    def test_the_interval_is_floored_at_a_second(self):
        self.assertEqual(ReplicaLagGate(0.4).sample_interval, 1.0)

    def test_the_first_sample_is_due(self):
        self.assertTrue(ReplicaLagGate(30.0).due_for_sample())

    def test_a_second_sample_is_throttled(self):
        gate = ReplicaLagGate(30.0)
        self.assertTrue(gate.due_for_sample())
        self.assertFalse(gate.due_for_sample())

    def test_only_one_of_many_racing_readers_samples(self):
        gate = ReplicaLagGate(30.0)
        self.assertEqual(sum(1 for _ in range(50) if gate.due_for_sample()), 1)

    def test_a_demoted_gate_still_becomes_due(self):
        """Sampling is the only thing that reopens a replica cursor while
        demoted, so it is what lets the gate ever notice recovery."""
        gate = ReplicaLagGate(30.0, sample_interval=0.0)
        gate.due_for_sample()
        gate.record(90.0)
        self.assertFalse(gate.allows())
        self.assertTrue(gate.due_for_sample())


class TestLagSql(unittest.TestCase):
    """The SQL is the correctness argument; pin its shape."""

    def test_it_reports_zero_when_everything_received_is_replayed(self):
        self.assertIn("pg_last_wal_receive_lsn() = pg_last_wal_replay_lsn()", LAG_SQL)

    def test_it_reports_zero_on_a_primary(self):
        """``test_enable`` and ``dev_mode=replica`` point the readonly
        connection at the primary; that is zero seconds behind itself."""
        self.assertIn("NOT pg_is_in_recovery()", LAG_SQL)

    def test_it_falls_back_to_the_replay_timestamp_only_when_behind(self):
        self.assertIn("pg_last_xact_replay_timestamp()", LAG_SQL)
        receive_check = LAG_SQL.index("pg_last_wal_receive_lsn")
        timestamp_use = LAG_SQL.index("pg_last_xact_replay_timestamp")
        self.assertLess(
            receive_check,
            timestamp_use,
            "the caught-up check must come first, or an idle primary reads as lag",
        )

    def test_it_never_returns_null(self):
        """``pg_last_xact_replay_timestamp()`` is NULL just after startup."""
        self.assertIn("coalesce(", LAG_SQL)

    def test_it_never_returns_a_negative(self):
        self.assertIn("greatest(", LAG_SQL)


class TestSnapshot(unittest.TestCase):
    def test_a_disabled_gate_reports_disabled(self):
        snap = ReplicaLagGate(0.0).snapshot()
        self.assertFalse(snap["enabled"])
        self.assertFalse(snap["lagging"])

    def test_a_lagging_gate_reports_its_measurement(self):
        gate = ReplicaLagGate(10.0)
        gate.record(42.5)
        snap = gate.snapshot()
        self.assertTrue(snap["enabled"])
        self.assertTrue(snap["lagging"])
        self.assertEqual(snap["last_lag_seconds"], 42.5)
        self.assertEqual(snap["max_lag_seconds"], 10.0)


if __name__ == "__main__":
    unittest.main()
