import threading
from typing import NamedTuple

from odoo.libs.debug_log import DebugLog

__all__ = ["CircuitEntry", "EsbuildCircuit"]

_debug = DebugLog(__name__)


class CircuitEntry(NamedTuple):
    expiry: float
    reason: str
    failures: int


class EsbuildCircuit:
    ESCALATE_AFTER = 2

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
        with self._lock:
            entry = self._entries.get(key)
        if entry is None:
            return True, ""
        if now < entry.expiry:
            _debug.logic(
                "esbuild_circuit.open",
                db=key[0],
                bundle=key[1],
                reason=entry.reason,
                failures=entry.failures,
                remaining_s=entry.expiry - now,
            )
            return False, entry.reason
        _debug.logic(
            "esbuild_circuit.expired", db=key[0], bundle=key[1], failures=entry.failures
        )
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
        _debug.lifecycle(
            "esbuild_circuit.tripped",
            db=key[0],
            bundle=key[1],
            reason=reason,
            failures=failures,
            cooldown_s=cooldown,
            escalated=failures >= self.escalate_after,
        )
        return entry

    def record_success(self, key: tuple[str, str]) -> bool:
        with self._lock:
            entry = self._entries.pop(key, None)
        if _debug.lifecycle.enabled and entry is not None:
            _debug.lifecycle(
                "esbuild_circuit.reset",
                db=key[0],
                bundle=key[1],
                failures=entry.failures,
            )
        return entry is not None

    def clear_database_entries(self, dbname: str) -> int:
        with self._lock:
            stale = [key for key in self._entries if key[0] == dbname]
            for key in stale:
                del self._entries[key]
        _debug.lifecycle("esbuild_circuit.db_cleared", db=dbname, entries=len(stale))
        return len(stale)

    def entry(self, key: tuple[str, str]) -> CircuitEntry | None:
        with self._lock:
            return self._entries.get(key)

    def snapshot(self) -> dict[tuple[str, str], CircuitEntry]:
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
        with self._lock:
            return key in self._entries

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def _evict(self, now: float, *, keep: tuple[str, str]) -> None:
        ordered = sorted(
            self._entries.items(), key=lambda kv: (kv[1].expiry > now, kv[1].expiry)
        )
        for key, _entry in ordered:
            if len(self._entries) <= self.max_entries:
                return
            if key != keep:
                del self._entries[key]
