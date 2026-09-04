from __future__ import annotations

import logging
import typing

import psycopg

from .breaker import CircuitBreaker
from .lag import LAG_SQL, ReplicaLagGate
from .pool import PoolError
from .settings import PoolSettings, current

if typing.TYPE_CHECKING:
    from .cursor import BaseCursor
    from .pool import Connection

_logger = logging.getLogger(__name__)

REPLICA_RETRY_TIME = 20 * 60

CursorMode = typing.Literal["ro", "ro->rw", "rw"]


def is_readonly_cursor_enabled(settings: PoolSettings | None = None) -> bool:
    return (settings if settings is not None else current()).readonly_cursors


class ReplicaRouter:
    __slots__ = ("breaker", "lag", "primary", "readonly")

    def __init__(
        self,
        primary: Connection,
        readonly: Connection | None = None,
        *,
        max_lag: float = 0.0,
        breaker: CircuitBreaker | None = None,
        lag: ReplicaLagGate | None = None,
    ) -> None:
        self.primary = primary
        self.readonly = readonly
        self.breaker = (
            breaker
            if breaker is not None
            else CircuitBreaker(max_cooldown=REPLICA_RETRY_TIME)
        )
        self.lag = lag if lag is not None else ReplicaLagGate(max_lag)

    def cursor(self, readonly: bool = False) -> tuple[BaseCursor, CursorMode]:
        if not readonly or self.readonly is None:
            return self.primary.cursor(), "rw"
        cr = self._replica_cursor(self.readonly)
        if cr is not None:
            return cr, "ro"
        return self.primary.cursor(), "ro->rw"

    def _replica_cursor(self, replica: Connection) -> BaseCursor | None:
        sample_due = self.lag.is_sample_due()
        if not (self.lag.is_replica_usable() or sample_due):
            return None
        if not self.breaker.acquire_attempt():
            return None
        try:
            cr = replica.cursor()
        except psycopg.OperationalError, PoolError:
            self.breaker.record_failure()
            _logger.warning(
                "Failed to open a readonly cursor, falling back to the "
                "read-write cursor and retrying the replica in %.0fs "
                "(failure %d)",
                self.breaker.cooldown_remaining,
                self.breaker.failures,
            )
            return None
        if not self.breaker.closed:
            _logger.info("Replica reachable again, resuming readonly cursors")
        self.breaker.record_success()
        if sample_due and self.lag.acquire_sample_interval():
            self._sample_lag(cr)
        if self.lag.is_replica_usable():
            return cr
        cr.close()
        return None

    def _sample_lag(self, cr: BaseCursor) -> None:
        try:
            cr.execute(LAG_SQL)  # noqa: E8501  LAG_SQL is a module constant
            row = cr.fetchone()
            measured = row[0] if row else None
        except Exception:
            _logger.debug("Could not measure replica lag", exc_info=True)
            measured = None
        was_allowed = self.lag.is_replica_usable()
        self.lag.record(measured)
        if was_allowed and not self.lag.is_replica_usable():
            _logger.warning(
                "Replica %.1fs behind (db_replica_max_lag=%.1fs); serving "
                "readonly requests from the primary until it catches up",
                self.lag.last_lag,
                self.lag.max_lag,
            )
        elif not was_allowed and self.lag.is_replica_usable():
            _logger.info(
                "Replica caught up (%.1fs behind); resuming readonly cursors",
                self.lag.last_lag,
            )
