"""Tier-2 tests for the replica gating in ``Registry.cursor(readonly=True)``.

Real ``import odoo``, stub connections, no database.

``Registry.cursor`` used to record one replica failure and route *every*
read-only request to the primary for a flat 20 minutes, with nothing
re-checking.  A transient blip — a failover, a brief partition, one
``PoolTimeout`` under load — therefore cost 20 minutes of unnecessary primary
load, and recovery was waited out rather than detected.

What replaces it is a :class:`~odoo.db.breaker.CircuitBreaker`, so these pin the
behaviour that changed: the fallback still happens, it stops attempting a replica
already known to be down, and it comes back on its own.  The breaker's schedule
itself is covered in ``odoo/db/tests/test_breaker.py``; against a live streaming
replica the round trip measured 5.1s where the flat window would have been 1200.
"""

import threading

import psycopg
import pytest

import odoo.db
from odoo.db.breaker import CircuitBreaker
from odoo.db.lag import ReplicaLagGate
from odoo.orm.runtime.registry import _REPLICA_RETRY_TIME, Registry


class _Conn:
    """Stands in for ``odoo.db.Connection``; counts cursor attempts."""

    def __init__(self, label, fails=False):
        self.label = label
        self.fails = fails
        self.attempts = 0

    def cursor(self):
        self.attempts += 1
        if self.fails:
            raise psycopg.OperationalError(f"{self.label} is down")
        return f"{self.label}-cursor"


def _make_registry(*, replica_fails=False, with_replica=True, max_lag=0.0):
    reg = object.__new__(Registry)
    reg.db_name = "_breaker_db"
    reg._db = _Conn("primary")
    reg._db_readonly = _Conn("replica", fails=replica_fails) if with_replica else None
    reg._replica_breaker = CircuitBreaker(max_cooldown=_REPLICA_RETRY_TIME)
    reg._replica_lag = ReplicaLagGate(max_lag)
    return reg


def test_a_healthy_replica_serves_readonly_cursors():
    reg = _make_registry()
    assert reg.cursor(readonly=True) == "replica-cursor"
    assert reg._replica_breaker.closed


def test_no_replica_configured_uses_the_primary():
    reg = _make_registry(with_replica=False)
    assert reg.cursor(readonly=True) == "primary-cursor"


def test_readwrite_never_touches_the_replica():
    reg = _make_registry()
    assert reg.cursor(readonly=False) == "primary-cursor"
    assert reg._db_readonly.attempts == 0


def test_a_failing_replica_falls_back_and_opens_the_breaker():
    reg = _make_registry(replica_fails=True)
    assert reg.cursor(readonly=True) == "primary-cursor"
    assert not reg._replica_breaker.closed
    assert reg._replica_breaker.failures == 1


def test_a_downed_replica_is_not_re_attempted_while_the_breaker_is_open():
    """The flat window did this too; what matters is that it still holds, so a
    dead replica does not draw a connection attempt from every request."""
    reg = _make_registry(replica_fails=True)
    for _ in range(20):
        assert reg.cursor(readonly=True) == "primary-cursor"
    assert reg._db_readonly.attempts == 1


def test_it_recovers_without_waiting_out_the_ceiling():
    reg = _make_registry(replica_fails=True)
    reg.cursor(readonly=True)
    assert reg._db_readonly.attempts == 1

    reg._db_readonly.fails = False
    reg._replica_breaker._opened_at -= reg._replica_breaker.initial_cooldown + 1

    assert reg.cursor(readonly=True) == "replica-cursor"
    assert reg._replica_breaker.closed, "a working probe must close the breaker"
    assert reg._replica_breaker.failures == 0, "and reset the backoff"


def test_repeated_failures_do_not_exceed_the_old_flat_window():
    reg = _make_registry(replica_fails=True)
    breaker = reg._replica_breaker
    for _ in range(40):
        breaker._opened_at -= breaker.max_cooldown + 1
        reg.cursor(readonly=True)
    assert breaker.cooldown_remaining <= _REPLICA_RETRY_TIME


def test_pool_errors_are_treated_as_replica_failures():
    """``PoolError`` is what saturation or an unreachable host actually raises
    through the pool, so it must gate the replica like an OperationalError."""

    class _PoolFail(_Conn):
        def cursor(self):
            self.attempts += 1
            raise odoo.db.PoolError("no connection")

    reg = _make_registry()
    reg._db_readonly = _PoolFail("replica")
    assert reg.cursor(readonly=True) == "primary-cursor"
    assert not reg._replica_breaker.closed


def test_the_cursor_mode_marker_records_the_demotion():
    """The HTTP layer reads ``cursor_mode`` to know a readonly route ran on the
    primary, so the marker must survive the switch to the breaker."""
    reg = _make_registry(replica_fails=True)
    thread = threading.current_thread()
    thread.cursor_mode = "unset"
    try:
        reg.cursor(readonly=True)
        assert thread.cursor_mode == "ro->rw"
        reg._db_readonly.fails = False
        reg._replica_breaker.record_success()
        reg.cursor(readonly=True)
        assert thread.cursor_mode == "ro"
    finally:
        del thread.cursor_mode


def test_the_flat_retry_window_is_gone():
    reg = _make_registry()
    assert not hasattr(reg, "_db_readonly_failed_time"), (
        "the flat 20-minute demotion was replaced by the breaker"
    )


if __name__ == "__main__":
    pytest.main([__file__])


class _LagConn(_Conn):
    """A replica cursor that answers the lag query with a fixed measurement."""

    def __init__(self, label, lag=0.0):
        super().__init__(label)
        self.lag = lag
        self.queries = 0

    def cursor(self):
        self.attempts += 1
        return _LagCursor(self)


class _LagCursor:
    def __init__(self, conn):
        self._conn = conn
        self.closed = False

    def execute(self, *args, **kwargs):
        self._conn.queries += 1

    def fetchone(self):
        return (self._conn.lag,)

    def close(self):
        self.closed = True


def _lag_registry(lag, max_lag):
    reg = _make_registry(max_lag=max_lag)
    reg._db_readonly = _LagConn("replica", lag=lag)
    return reg


def test_a_current_replica_serves_reads():
    reg = _lag_registry(lag=1.0, max_lag=30.0)
    assert isinstance(reg.cursor(readonly=True), _LagCursor)
    assert reg._replica_lag.allows()


def test_a_lagging_replica_is_demoted_to_the_primary():
    reg = _lag_registry(lag=120.0, max_lag=30.0)
    assert reg.cursor(readonly=True) == "primary-cursor"
    assert not reg._replica_lag.allows()


def test_the_rejected_replica_cursor_is_closed_not_leaked():
    """It was borrowed from the pool to take the measurement; dropping it on the
    floor would hold a permit until garbage collection."""
    reg = _lag_registry(lag=120.0, max_lag=30.0)
    conn = reg._db_readonly
    opened = []
    original = conn.cursor

    def spy():
        cr = original()
        opened.append(cr)
        return cr

    conn.cursor = spy
    reg.cursor(readonly=True)
    assert opened and all(cr.closed for cr in opened)


def test_a_disabled_ceiling_never_queries_for_lag():
    reg = _lag_registry(lag=9999.0, max_lag=0.0)
    reg.cursor(readonly=True)
    assert reg._db_readonly.queries == 0, "db_replica_max_lag=0 must cost nothing"


def test_the_verdict_is_cached_between_samples():
    reg = _lag_registry(lag=1.0, max_lag=120.0)
    for _ in range(10):
        reg.cursor(readonly=True)
    assert reg._db_readonly.queries == 1, "one measurement per sample interval"


def test_a_demoted_gate_recovers_when_the_replica_catches_up():
    reg = _lag_registry(lag=120.0, max_lag=30.0)
    reg._replica_lag.sample_interval = 0.0
    assert reg.cursor(readonly=True) == "primary-cursor"
    reg._db_readonly.lag = 2.0
    assert isinstance(reg.cursor(readonly=True), _LagCursor)
    assert reg._replica_lag.allows()


def test_an_unreadable_measurement_does_not_demote():
    class _Boom(_LagConn):
        def cursor(self):
            self.attempts += 1
            cr = _LagCursor(self)
            cr.execute = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
            return cr

    reg = _make_registry(max_lag=30.0)
    reg._db_readonly = _Boom("replica")
    assert isinstance(reg.cursor(readonly=True), _LagCursor)
    assert reg._replica_lag.allows()


def test_a_lag_demotion_does_not_consume_the_breakers_probe():
    """``breaker.allow()`` *claims* the half-open probe, so it must be asked
    only once the lag gate has already agreed to use the replica — otherwise a
    demotion burns the claim without probing and wedges the breaker until the
    claim is deemed abandoned."""
    reg = _lag_registry(lag=120.0, max_lag=30.0)
    breaker = reg._replica_breaker
    breaker.record_failure()
    breaker._opened_at -= breaker.initial_cooldown + 1

    lag = reg._replica_lag
    lag.record(120.0)
    lag.due_for_sample()
    lag.sample_interval = 1e9
    assert not lag.allows() and not lag.due_for_sample(), "demoted, no sample due"

    assert reg.cursor(readonly=True) == "primary-cursor"
    assert breaker._probing_since == 0.0, "the probe claim must be untouched"
    assert breaker.allow(), "a real probe must still be grantable"
