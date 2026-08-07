from __future__ import annotations

import threading
from time import monotonic
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

_LAST_BORROW_ATTR = "_odoo_last_borrow"


def note_activity(pool) -> None:
    setattr(pool, _LAST_BORROW_ATTR, monotonic())


def checked_out(pool) -> int:
    stats = pool.get_stats()
    return stats.get("pool_size", 0) - stats.get("pool_available", 0)


class IdlePoolReaper:
    __slots__ = ("_last_check", "check_interval", "ttl")

    def __init__(self, ttl: float):
        self.ttl = ttl
        self.check_interval = max(1.0, ttl / 4) if ttl > 0 else 0.0
        self._last_check = 0.0

    @property
    def enabled(self) -> bool:
        return self.ttl > 0

    def due(self) -> bool:
        if self.check_interval <= 0:
            return False
        now = monotonic()
        if now - self._last_check < self.check_interval:
            return False
        self._last_check = now
        return True

    def probably_due(self) -> bool:
        if self.check_interval <= 0:
            return False
        return monotonic() - self._last_check >= self.check_interval

    def collect(self, pools: Mapping[Any, Any], exclude_key: Any = None) -> list:
        if not self.enabled:
            return []
        now = monotonic()
        reapable = []
        for key, pool in pools.items():
            if key == exclude_key:
                continue
            if now - getattr(pool, _LAST_BORROW_ATTR, now) <= self.ttl:
                continue
            if checked_out(pool) > 0:
                continue
            reapable.append(key)
        return reapable

    @staticmethod
    def close_in_background(target, pools: list, name: str) -> None:
        threading.Thread(target=target, args=(pools,), name=name, daemon=True).start()
