"""The circuit breaker that decides whether esbuild is worth attempting.

Kept apart from `ir.qweb` because it is a state machine over a clock and a
counter, and because it had already been wrong twice in ways a unit test would
have caught at once: the failure counter was updated without synchronisation,
and the half-open state rewrote its own entry on every read.

The transition rules, in full:

- **closed** -- no entry.  Attempt the compile.
- **open** -- an entry whose expiry is in the future.  Decline, and say why.
- **half-open** -- an entry whose expiry has passed.  Attempt the compile, but
  keep the entry: its failure count is what escalates the *next* cooldown, and
  losing it on the first success-or-failure would make the escalation
  unreachable for a bundle that fails intermittently.
- A success closes the circuit and forgets the count.

`record_failure` takes **both** candidate cooldowns rather than a callback,
because choosing between them depends on the failure count and the count is
only knowable inside the critical section.  The model used to read the count
under a lock, release it to read `ir.config_parameter` -- a database round trip
-- and re-acquire to write, so two workers failing together both observed
"first failure" and the extended cooldown was never reached.
"""

import threading
from typing import NamedTuple

__all__ = ["CircuitEntry", "EsbuildCircuit"]


class CircuitEntry(NamedTuple):
    expiry: float
    reason: str
    failures: int


class EsbuildCircuit:
    #: Failures at or above this count earn the extended cooldown.
    ESCALATE_AFTER = 2

    #: Entries are keyed `(database, bundle)` and only a success removes one,
    #: so a host that creates and drops databases would otherwise accumulate
    #: them for the life of the process.  Expired entries are evicted first:
    #: all they still carry is a failure count, which is a heuristic.
    MAX_ENTRIES = 2048

    def __init__(
        self, *, escalate_after: int | None = None, max_entries: int | None = None
    ) -> None:
        self._entries: dict[tuple[str, str], CircuitEntry] = {}
        self._lock = threading.Lock()
        self.escalate_after = (
            self.ESCALATE_AFTER if escalate_after is None else escalate_after
        )
        self.max_entries = self.MAX_ENTRIES if max_entries is None else max_entries

    def state(self, key: tuple[str, str], *, now: float) -> tuple[bool, str]:
        """``(may_attempt, reason)``. The reason is empty unless it declines.

        Read without the lock, deliberately: this runs on every render, and a
        torn read can only mean "attempt the compile", which is the safe answer
        and the one a closed circuit gives anyway.
        """
        entry = self._entries.get(key)
        if entry is None:
            return True, ""
        if now < entry.expiry:
            return False, entry.reason
        return True, ""

    def record_failure(
        self,
        key: tuple[str, str],
        reason: str,
        *,
        now: float,
        cooldown_s: float,
        extended_cooldown_s: float,
    ) -> CircuitEntry:
        with self._lock:
            previous = self._entries.get(key)
            failures = (previous.failures + 1) if previous else 1
            cooldown = (
                extended_cooldown_s if failures >= self.escalate_after else cooldown_s
            )
            entry = CircuitEntry(now + cooldown, reason, failures)
            self._entries[key] = entry
            if len(self._entries) > self.max_entries:
                self._evict(now, keep=key)
        return entry

    def record_success(self, key: tuple[str, str]) -> bool:
        """``True`` when this actually closed an open or half-open circuit."""
        with self._lock:
            return self._entries.pop(key, None) is not None

    def forget_database(self, dbname: str) -> int:
        with self._lock:
            stale = [key for key in self._entries if key[0] == dbname]
            for key in stale:
                del self._entries[key]
        return len(stale)

    def entry(self, key: tuple[str, str]) -> CircuitEntry | None:
        return self._entries.get(key)

    def snapshot(self) -> dict[tuple[str, str], CircuitEntry]:
        """A copy, for a test that has to put the process state back."""
        with self._lock:
            return dict(self._entries)

    def restore(self, entries: dict[tuple[str, str], CircuitEntry]) -> None:
        with self._lock:
            self._entries.clear()
            self._entries.update(entries)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __contains__(self, key: object) -> bool:
        return key in self._entries

    def __len__(self) -> int:
        return len(self._entries)

    def _evict(self, now: float, *, keep: tuple[str, str]) -> None:
        # Caller holds the lock.  Expired first, oldest expiry first within
        # each group, and never `keep` -- evicting the entry we were just asked
        # to record would make the breaker forget the very failure that
        # triggered it, which is worse than being over the cap by one.
        ordered = sorted(
            self._entries.items(), key=lambda kv: (kv[1].expiry > now, kv[1].expiry)
        )
        for key, _entry in ordered:
            if len(self._entries) <= self.max_entries:
                return
            if key != keep:
                del self._entries[key]
