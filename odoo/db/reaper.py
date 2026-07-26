"""Idle-pool reaping policy for :class:`~odoo.db.pool.ConnectionPool`.

Split out of :mod:`odoo.db.pool` so the *decision* — which per-DSN pools have
been quiet long enough to close, and when it is worth asking — is a small unit
testable against a stand-in, separate from the locking and teardown mechanics
that must stay with the pool registry that owns them.

The policy exists because a process serving many databases over time would
otherwise accumulate one psycopg_pool per database it ever touched, each with
its own worker threads and idle connections, with nothing to collect the ones
for databases that went quiet or were dropped.
"""

from __future__ import annotations

import threading
from time import monotonic
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

_LAST_BORROW_ATTR = "_odoo_last_borrow"


def note_activity(pool) -> None:
    """Stamp *pool* as freshly active.

    The single place the ``_LAST_BORROW_ATTR`` stamp is written.  Called on
    EVERY borrow and EVERY return: a pool that just handed out or took back a
    connection is active, not idle, and must not be reaped out from under its
    next user.  Stamping on return — not only on borrow — is what stops a
    connection held longer than the TTL and then returned from leaving its pool
    with a stale stamp that the next sweep reaps.  ``setattr`` is atomic under
    the GIL, so this needs no lock.
    """
    setattr(pool, _LAST_BORROW_ATTR, monotonic())


def checked_out(pool) -> int:
    """Connections *pool* currently has handed out (size minus available).

    Once a pool has been idle past the reap TTL this reading is reliable: any
    async ``reset`` from a recent return has long since drained, so a non-zero
    value is a genuine hold (e.g. a cron ``LISTEN``), not a transient.  Single
    source of truth for the ``pool_size - pool_available`` formula.
    """
    stats = pool.get_stats()
    return stats.get("pool_size", 0) - stats.get("pool_available", 0)


class IdlePoolReaper:
    """Decides which idle per-DSN pools to close, and how often to look.

    Owns the TTL, the sweep throttle and the activity stamps.  Deliberately does
    NOT own the pools dict or its lock: reaping mutates the registry the pool
    hands out connections from, so the caller keeps that under its own lock and
    only asks this object *what* is reapable.
    """

    __slots__ = ("_last_check", "check_interval", "ttl")

    def __init__(self, ttl: float):
        self.ttl = ttl
        self.check_interval = max(1.0, ttl / 4) if ttl > 0 else 0.0
        self._last_check = 0.0

    @property
    def enabled(self) -> bool:
        """Whether reaping runs at all (``db_pool_reap_idle`` of 0 disables it)."""
        return self.ttl > 0

    def due(self) -> bool:
        """Whether a sweep is worth doing now, and claim the slot if so.

        Throttles the hot-path sweep to once per :attr:`check_interval`.  The
        caller must hold its registry lock: the read-and-stamp has to be atomic
        or two returning threads both sweep.
        """
        if self.check_interval <= 0:
            return False
        now = monotonic()
        if now - self._last_check < self.check_interval:
            return False
        self._last_check = now
        return True

    def probably_due(self) -> bool:
        """Lock-free pre-check for the hot path, so the common return takes none."""
        if self.check_interval <= 0:
            return False
        return monotonic() - self._last_check >= self.check_interval

    def collect(self, pools: Mapping[Any, Any], exclude_key: Any = None) -> list:
        """Keys of the pools in *pools* that are safe to close.

        A pool is reapable when BOTH: it has seen no activity — borrow or
        return — in the last :attr:`ttl` seconds (so none can be in flight), and
        it holds no checked-out connection (:func:`checked_out` ``== 0``,
        reliable once idle past the TTL).

        *exclude_key* is the pool the caller is about to use and must never reap
        (the cold path passes the just-created key); ``None`` excludes nothing —
        on the return sweep the just-returned pool is protected because the
        caller re-stamps it through :func:`note_activity` first.
        """
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
        """Run *target* over *pools* off the caller's thread.

        Closing a psycopg_pool joins its worker threads, which must not happen
        inline on the connection-return path.
        """
        threading.Thread(target=target, args=(pools,), name=name, daemon=True).start()
