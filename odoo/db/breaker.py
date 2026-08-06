"""Failure gating for an optional database endpoint (today: the read replica).

``Registry.cursor(readonly=True)`` used to record one failure and send *every*
read-only request to the primary for a flat 20 minutes.  That is the wrong shape
twice over: a transient blip — a failover, a brief partition, one ``PoolTimeout``
under load — costs 20 minutes of unnecessary primary load, and nothing ever
re-checks, so recovery is waited out rather than detected.

A breaker fixes both ends.  The first failure opens it for a second; if the
replica is genuinely down each probe doubles the wait up to the same 20-minute
ceiling, so the worst case is no worse than before while a blip recovers almost
immediately.  Only one caller probes at a time, so a dead replica cannot draw a
thundering herd of connection attempts from every request that arrives while it
is out.

Pure state machine — no socket, no pool, no clock but ``monotonic`` — so the
schedule is testable without a replica.
"""

from __future__ import annotations

import threading
from time import monotonic

_INITIAL_COOLDOWN = 1.0

_PROBE_ABANDON_AFTER = 60.0
"""How long a claimed probe may run before another caller may reclaim it.

Deliberately independent of the cooldown: tying the two meant a breaker with a
zero-width window could not hold a claim at all, so every caller probed at once —
the thundering herd the claim exists to prevent.  It only ever applies after the
cooldown has already elapsed, so it cannot shorten a backoff.
"""


class CircuitBreaker:
    """Closed while healthy; opens on failure with exponential backoff.

    Three states, though only two are visible to a caller.  **Closed**:
    :meth:`allow` is always true.  **Open**: false until the cooldown elapses.
    **Half-open**: the cooldown has elapsed and exactly one caller is granted a
    probe; everyone else keeps failing fast until that probe reports back
    through :meth:`record_success` or :meth:`record_failure`.

    A probe that never reports — a caller that raises something the wiring does
    not catch — would otherwise wedge the breaker half-open forever, so a claim
    older than :data:`_PROBE_ABANDON_AFTER` is treated as abandoned and the next
    caller may probe again.
    """

    __slots__ = (
        "_cooldown",
        "_lock",
        "_open",
        "_opened_at",
        "_probing_since",
        "failures",
        "initial_cooldown",
        "max_cooldown",
        "trips",
    )

    def __init__(
        self, max_cooldown: float, initial_cooldown: float = _INITIAL_COOLDOWN
    ):
        if max_cooldown < initial_cooldown:
            raise ValueError(
                f"max_cooldown ({max_cooldown}) must be >= "
                f"initial_cooldown ({initial_cooldown})"
            )
        self.initial_cooldown = initial_cooldown
        self.max_cooldown = max_cooldown
        self._lock = threading.Lock()
        self._open = False
        self._cooldown = 0.0
        self._opened_at = 0.0
        self._probing_since = 0.0
        self.failures = 0
        self.trips = 0

    @property
    def closed(self) -> bool:
        """Whether the endpoint is currently considered healthy.

        An explicit flag rather than ``_cooldown == 0``: that conflated
        "healthy" with "zero-width window", so a breaker configured to retry
        immediately reported itself closed and never gated anything.
        """
        return not self._open

    @property
    def cooldown_remaining(self) -> float:
        """Seconds until the next probe is allowed (``0`` when closed)."""
        if self.closed:
            return 0.0
        return max(0.0, self._opened_at + self._cooldown - monotonic())

    def allow(self) -> bool:
        """Whether this caller may use the endpoint, claiming the probe if open."""
        with self._lock:
            if self.closed:
                return True
            now = monotonic()
            if now - self._opened_at < self._cooldown:
                return False
            if self._probing_since and now - self._probing_since < _PROBE_ABANDON_AFTER:
                return False
            self._probing_since = now
            return True

    def record_success(self) -> None:
        """Report the endpoint working: close the breaker and reset the backoff."""
        with self._lock:
            self._open = False
            self._cooldown = 0.0
            self._opened_at = 0.0
            self._probing_since = 0.0
            self.failures = 0

    def record_failure(self) -> None:
        """Report the endpoint failing: open, or widen a *probed* open window.

        The window doubles once per **probe cycle**, not once per failure — the
        distinction the module docstring draws ("each probe doubles the wait").
        They differ only on the initial trip: every request that passed
        :meth:`allow` while the breaker was still closed is in flight against a
        replica that then goes down, and each fails (after up to
        ``db_borrow_timeout``) and lands here. Doubling on every one of those
        turned a single blip with N concurrent requests into N doublings — a
        2-second outage could open a 20-minute window. Once the breaker is open,
        :meth:`allow` hands a probe to exactly one caller, so a widening failure
        is one that reports back against an outstanding probe (``_probing_since``
        set); a failure with no probe outstanding is a pile-on straggler and is
        counted but does not move the window.
        """
        with self._lock:
            self.failures += 1
            if not self._open:
                # First failure from the closed state: trip the breaker.
                self._open = True
                self._cooldown = self.initial_cooldown
                self._opened_at = monotonic()
                self._probing_since = 0.0
                self.trips += 1
                return
            if self._probing_since:
                # A granted probe failed again: a genuine new cycle — widen.
                self._cooldown = min(self._cooldown * 2, self.max_cooldown)
                self._opened_at = monotonic()
                self._probing_since = 0.0
            # else: a pile-on straggler (a request that passed allow() before
            # the trip, or arrived after a probe already reported). Counted
            # above, but it must not widen or slide the window.

    def snapshot(self) -> dict:
        """State for ``pool_health()`` and logs."""
        return {
            "closed": self.closed,
            "failures": self.failures,
            "trips": self.trips,
            "cooldown_seconds": round(self._cooldown, 3),
            "cooldown_remaining_seconds": round(self.cooldown_remaining, 3),
        }
