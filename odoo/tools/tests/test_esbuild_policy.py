import threading

import pytest

from odoo.tools.assets.esbuild_policy import CircuitEntry, EsbuildCircuit

KEY = ("db", "web.assets_web")
OTHER = ("db", "web.assets_frontend")


@pytest.fixture
def circuit():
    return EsbuildCircuit()


class TestTransitions:
    def test_an_unknown_bundle_may_attempt(self, circuit):
        assert circuit.state(KEY, now=0.0) == (True, "")

    def test_a_failure_opens_the_circuit(self, circuit):
        circuit.record_failure(
            KEY, "TimeoutExpired", now=100.0, cooldown_s=60.0, extended_cooldown_s=600.0
        )
        assert circuit.state(KEY, now=100.0) == (False, "TimeoutExpired")
        assert circuit.state(KEY, now=159.9) == (False, "TimeoutExpired")

    def test_the_cooldown_expires_into_half_open(self, circuit):
        circuit.record_failure(
            KEY, "boom", now=100.0, cooldown_s=60.0, extended_cooldown_s=600.0
        )
        assert circuit.state(KEY, now=160.0) == (True, "")

    def test_half_open_keeps_its_entry(self, circuit):
        """The failure count is what escalates the *next* cooldown, so an
        expired entry must survive being read.  It also must not be rewritten
        on every read, which is a dict write per render for no effect."""
        circuit.record_failure(
            KEY, "boom", now=100.0, cooldown_s=60.0, extended_cooldown_s=600.0
        )
        before = circuit._entries[KEY]
        for _ in range(5):
            assert circuit.state(KEY, now=999.0) == (True, "")
        assert circuit._entries[KEY] == before

    def test_a_success_closes_and_forgets(self, circuit):
        circuit.record_failure(
            KEY, "boom", now=0.0, cooldown_s=60.0, extended_cooldown_s=600.0
        )
        assert circuit.record_success(KEY) is True
        assert circuit.state(KEY, now=0.0) == (True, "")
        assert len(circuit) == 0

    def test_a_success_on_a_closed_circuit_reports_nothing_to_close(self, circuit):
        assert circuit.record_success(KEY) is False

    def test_bundles_are_independent(self, circuit):
        circuit.record_failure(
            KEY, "boom", now=0.0, cooldown_s=60.0, extended_cooldown_s=600.0
        )
        assert circuit.state(OTHER, now=0.0) == (True, "")


class TestEscalation:
    def test_the_first_failure_takes_the_short_cooldown(self, circuit):
        entry = circuit.record_failure(
            KEY, "boom", now=0.0, cooldown_s=60.0, extended_cooldown_s=600.0
        )
        assert entry == CircuitEntry(60.0, "boom", 1)

    def test_the_second_failure_takes_the_extended_one(self, circuit):
        circuit.record_failure(
            KEY, "boom", now=0.0, cooldown_s=60.0, extended_cooldown_s=600.0
        )
        entry = circuit.record_failure(
            KEY, "boom", now=100.0, cooldown_s=60.0, extended_cooldown_s=600.0
        )
        assert entry == CircuitEntry(700.0, "boom", 2)

    def test_the_count_survives_the_cooldown_expiring(self, circuit):
        circuit.record_failure(
            KEY, "boom", now=0.0, cooldown_s=60.0, extended_cooldown_s=600.0
        )
        assert circuit.state(KEY, now=9999.0)[0] is True
        entry = circuit.record_failure(
            KEY, "boom", now=9999.0, cooldown_s=60.0, extended_cooldown_s=600.0
        )
        assert entry.failures == 2
        assert entry.expiry == 9999.0 + 600.0

    def test_a_success_resets_the_escalation(self, circuit):
        circuit.record_failure(
            KEY, "boom", now=0.0, cooldown_s=60.0, extended_cooldown_s=600.0
        )
        circuit.record_success(KEY)
        entry = circuit.record_failure(
            KEY, "boom", now=0.0, cooldown_s=60.0, extended_cooldown_s=600.0
        )
        assert entry.failures == 1


class TestConcurrency:
    def test_simultaneous_failures_are_all_counted(self):
        """Read-modify-write used to straddle a database round trip: the model
        read the count under a lock, released it to read `ir.config_parameter`,
        and re-acquired to write.  Two workers failing together both observed
        "first failure", so the extended cooldown was never reached.  Passing
        both candidate cooldowns in keeps the whole decision in one critical
        section."""
        circuit = EsbuildCircuit()
        start = threading.Barrier(16)

        def fail():
            start.wait()
            circuit.record_failure(
                KEY, "boom", now=0.0, cooldown_s=60.0, extended_cooldown_s=600.0
            )

        threads = [threading.Thread(target=fail) for _ in range(16)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert circuit._entries[KEY].failures == 16

    def test_the_escalated_cooldown_is_reached_under_contention(self):
        circuit = EsbuildCircuit()
        start = threading.Barrier(8)
        seen = []

        def fail():
            start.wait()
            seen.append(
                circuit.record_failure(
                    KEY, "boom", now=0.0, cooldown_s=60.0, extended_cooldown_s=600.0
                ).expiry
            )

        threads = [threading.Thread(target=fail) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert sorted(seen) == [60.0] + [600.0] * 7


class TestBoundedGrowth:
    def test_entries_do_not_grow_without_limit(self):
        circuit = EsbuildCircuit(max_entries=8)
        for i in range(50):
            circuit.record_failure(
                ("db", f"b{i}"),
                "boom",
                now=0.0,
                cooldown_s=1.0,
                extended_cooldown_s=1.0,
            )
        assert len(circuit) <= 8

    def test_expired_entries_are_evicted_before_live_ones(self):
        circuit = EsbuildCircuit(max_entries=3)
        for i in range(3):
            circuit.record_failure(
                ("db", f"old{i}"),
                "boom",
                now=0.0,
                cooldown_s=1.0,
                extended_cooldown_s=1.0,
            )
        # now=100 leaves all three expired; a fresh failure must survive.
        circuit.record_failure(
            ("db", "fresh"),
            "boom",
            now=100.0,
            cooldown_s=60.0,
            extended_cooldown_s=60.0,
        )
        assert ("db", "fresh") in circuit._entries
        assert len(circuit) <= 3

    def test_the_entry_just_recorded_is_never_the_one_evicted(self):
        """Evicting it would make the breaker forget the very failure it was
        asked to record."""
        circuit = EsbuildCircuit(max_entries=2)
        for i in range(2):
            circuit.record_failure(
                ("db", f"live{i}"),
                "boom",
                now=0.0,
                cooldown_s=1e6,
                extended_cooldown_s=1e6,
            )
        # The newcomer's expiry is the shortest, so an ordering-only eviction
        # would pick it.
        circuit.record_failure(
            ("db", "newcomer"), "boom", now=0.0, cooldown_s=1.0, extended_cooldown_s=1.0
        )
        assert ("db", "newcomer") in circuit

    def test_a_dropped_database_can_be_forgotten(self):
        circuit = EsbuildCircuit()
        circuit.record_failure(
            ("gone", "b"), "boom", now=0.0, cooldown_s=1.0, extended_cooldown_s=1.0
        )
        circuit.record_failure(
            ("kept", "b"), "boom", now=0.0, cooldown_s=1.0, extended_cooldown_s=1.0
        )
        assert circuit.forget_database("gone") == 1
        assert list(circuit._entries) == [("kept", "b")]


class TestReadingSurface:
    def test_entry_reads_without_mutating(self, circuit):
        assert circuit.entry(KEY) is None
        written = circuit.record_failure(
            KEY, "boom", now=0.0, cooldown_s=60.0, extended_cooldown_s=600.0
        )
        assert circuit.entry(KEY) == written
        assert KEY in circuit
        assert OTHER not in circuit

    def test_snapshot_and_restore_round_trip(self, circuit):
        """A `TransactionCase` touching a process-wide breaker has to put it
        back; the old tests did it by copying a dict."""
        circuit.record_failure(
            KEY, "boom", now=0.0, cooldown_s=60.0, extended_cooldown_s=600.0
        )
        saved = circuit.snapshot()
        circuit.clear()
        assert len(circuit) == 0
        circuit.restore(saved)
        assert circuit.entry(KEY).failures == 1

    def test_a_snapshot_is_a_copy(self, circuit):
        circuit.record_failure(
            KEY, "boom", now=0.0, cooldown_s=60.0, extended_cooldown_s=600.0
        )
        saved = circuit.snapshot()
        circuit.clear()
        assert saved[KEY].failures == 1
