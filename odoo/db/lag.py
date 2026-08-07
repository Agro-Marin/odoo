"""Demote read-only traffic while the replica is too far behind.

``Registry.cursor(readonly=True)`` routes a request to the replica whenever one
is configured and reachable.  Reachable is not the same as *current*: a replica
30s behind serves 30s-stale reads with no signal and no policy.  Read-only
routes are chosen because they tolerate staleness, but "tolerates any amount,
unmeasured" is not a guarantee — ``db_replica_max_lag`` turns it into a bounded
one by sending reads back to the primary while the bound is exceeded.

Measuring the lag is the subtle part.  ``pg_last_xact_replay_timestamp()`` is
the timestamp of the last *replayed transaction*, so on an idle primary it grows
without bound on a replica that is perfectly caught up — measured 43s against a
standby with nothing left to apply.  Using it alone would demote a healthy
replica for the crime of having nothing to do.  :data:`LAG_SQL` therefore
reports zero whenever the standby has replayed everything it has received, and
falls back to the replay timestamp only when it genuinely has WAL outstanding.

What that cannot see is WAL the standby has not *received* — a network stall
looks identical to an idle primary from the standby's side.  Detecting it needs
``pg_stat_replication`` on the primary, which would mean a primary round-trip
per check and so defeat the point of asking at all.  The bound this gate
enforces is therefore on *apply* lag, which is the part a standby can know.
"""

from __future__ import annotations

import threading
from time import monotonic

LAG_SQL = """
    SELECT coalesce(
        CASE
            WHEN NOT pg_is_in_recovery() THEN 0
            WHEN pg_last_wal_receive_lsn() = pg_last_wal_replay_lsn() THEN 0
            ELSE greatest(
                0, extract(epoch FROM now() - pg_last_xact_replay_timestamp())
            )
        END, 0)::float8
"""
"""Apply lag in seconds, or ``0`` when the server has nothing outstanding.

Zero for a primary too (``NOT pg_is_in_recovery()``): ``test_enable`` and
``dev_mode=replica`` point the read-only connection at the primary on purpose,
and that is a replica zero seconds behind itself, not an error.
"""


class ReplicaLagGate:
    """Whether the replica is current enough to serve reads.

    Holds a sampled verdict rather than measuring per request: the measurement
    is a round-trip, and lag that matters persists for longer than one request.
    Between samples the cached answer applies, so an enabled gate costs one
    extra query per ``sample_interval`` and nothing in between.

    Disabled (``max_lag`` of 0) it allows everything and never asks for a
    sample, so the query is never issued at all.
    """

    __slots__ = (
        "_lagging",
        "_last_sample",
        "_lock",
        "last_lag",
        "max_lag",
        "sample_interval",
    )

    def __init__(self, max_lag: float, sample_interval: float | None = None):
        if max_lag < 0:
            raise ValueError(f"max_lag must be >= 0, got {max_lag}")
        self.max_lag = max_lag
        self.sample_interval = (
            sample_interval if sample_interval is not None else max(1.0, max_lag / 4)
        )
        self._lock = threading.Lock()
        self._last_sample = 0.0
        self._lagging = False
        self.last_lag = 0.0

    @property
    def enabled(self) -> bool:
        return self.max_lag > 0

    def allows(self) -> bool:
        """Whether the replica may serve reads, per the last sample."""
        return not (self.enabled and self._lagging)

    def due_for_sample(self) -> bool:
        """Whether the lag is worth re-measuring now, claiming the slot if so.

        Claimed rather than merely tested so concurrent readers issue one
        measurement between them, not one each.  While demoted this is also the
        only thing that reopens a replica cursor, so it is what lets the gate
        notice recovery.

        Nothing above this serialises: the gate hangs off the per-database
        :class:`~odoo.orm.runtime.Registry` singleton and
        ``Registry.cursor(readonly=True)`` calls it from every worker thread
        holding no lock.  So the read-and-stamp here is the only thing that can
        keep the claim, and it takes a lock -- as
        :meth:`~odoo.db.breaker.CircuitBreaker.allow` does for the same
        claim-the-probe pattern, and as :mod:`odoo.db.reaper` requires of its
        caller ("the read-and-stamp has to be atomic or two returning threads
        both sweep").

        **On a GIL build the lock is not what makes this correct today**, and
        that was measured rather than assumed: between the ``monotonic()`` call
        and the ``STORE_ATTR`` the compiled body contains no call and no
        backward jump, which are the only points CPython honours a GIL drop
        request, so the sequence cannot be preempted.  Racing the unlocked
        version -- 16 threads, 400 rounds, at switch intervals from 5 ms down to
        1 ns -- produced a duplicate claim exactly zero times, and against a real
        PostgreSQL 18 primary 16 concurrent readers issued one ``LAG_SQL``
        round-trip with or without it.

        It is here for the free-threaded build, where that bytecode-atomicity
        argument evaporates and the duplicate claim becomes a real data race
        costing one ``LAG_SQL`` round-trip per concurrent reader -- and, on the
        recovery path where a demoted gate lets a sampler through precisely
        because it claimed the slot, one replica cursor each.  Compare
        :mod:`odoo.db.stats`, which makes the opposite call for the same reason
        stated explicitly: its counters are only metrics, so it documents them as
        approximate under free-threading instead of paying for a lock.  The cost
        here is ~57 ns on an enabled gate and *nothing* on a disabled one
        (``db_replica_max_lag`` defaults to 0, so the early return above runs
        first and the lock is never reached).

        Single-sampling is also what lets :meth:`record` stay unlocked: with one
        claimant there is only ever one writer of ``last_lag``/``_lagging``.
        """
        if not self.enabled:
            return False
        with self._lock:
            now = monotonic()
            if self._last_sample and now - self._last_sample < self.sample_interval:
                return False
            self._last_sample = now
            return True

    def record(self, lag_seconds: float | None) -> None:
        """Store a measurement.  ``None`` (unmeasurable) is treated as healthy.

        A replica that cannot answer the lag query is a replica whose *failure*
        the breaker will see; refusing reads on an unreadable measurement would
        demote on the strength of no evidence.
        """
        self.last_lag = 0.0 if lag_seconds is None else max(0.0, lag_seconds)
        self._lagging = self.enabled and self.last_lag > self.max_lag

    def snapshot(self) -> dict:
        """State for ``pool_health()`` and logs."""
        return {
            "enabled": self.enabled,
            "max_lag_seconds": self.max_lag,
            "last_lag_seconds": round(self.last_lag, 3),
            "lagging": self._lagging,
        }
