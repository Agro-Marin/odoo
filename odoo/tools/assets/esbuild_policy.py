import threading
from typing import NamedTuple

__all__ = ["CircuitEntry", "EsbuildCircuit"]


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

    # Readers lock too. Every mutator here already did, and the asymmetry was
    # safe only for as long as a dict read is atomic -- which is a GIL
    # guarantee, and this tree is being written for a build where it is not
    # (ruff.toml: "preparing for 3.15 / PEP 703 free-threading"). state()
    # racing _evict() is the case: _evict deletes while state() reads.
    def state(self, key: tuple[str, str], *, now: float) -> tuple[bool, str]:
        with self._lock:
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
        with self._lock:
            return self._entries.pop(key, None) is not None

    def forget_database(self, dbname: str) -> int:
        with self._lock:
            stale = [key for key in self._entries if key[0] == dbname]
            for key in stale:
                del self._entries[key]
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
