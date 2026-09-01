from __future__ import annotations

import contextlib
import logging
import re
import time
import typing
from collections.abc import Iterable, Iterator

from odoo import db
from odoo.db import is_maintenance_db
from odoo.libs import backoff
from odoo.tools import SQL, OrderedSet, config
from odoo.tools.constants import CRON_TRIGGER_CHANNEL, JOB_QUEUE_CHANNEL

from ._limits import BACKOFF_BASE_S, BACKOFF_CEILING_S
from .db import list_dbs

if typing.TYPE_CHECKING:
    from odoo.db import BaseCursor

_logger = logging.getLogger("odoo.service.server")

__all__ = [
    "CRON_NOTIFY_JITTER_MAX_S",
    "CRON_POLL_INTERVAL_S",
    "CRON_TRIGGER_CHANNEL",
    "JOB_QUEUE_CHANNEL",
    "CronSchedule",
    "ReconnectBackoff",
    "arm_cron_listen",
    "close_cron_cursor",
    "drain_cron_notifies",
    "drain_swept_database",
    "get_cron_databases",
    "open_cron_listener",
    "order_notified_first",
]

CRON_POLL_INTERVAL_S = 60
"""How long a cron or job loop waits for a notify before sweeping anyway.

Named for what it is.  As `SLEEP_INTERVAL` in `_cron` it read as a generic
number and was borrowed by the back-off ceiling and by the threaded server's
reload grace period, so the three could not be tuned apart.
"""

CRON_NOTIFY_JITTER_MAX_S = 0.1


def arm_cron_listen(
    cr: BaseCursor,
    logger: logging.Logger,
    *,
    channel: str = CRON_TRIGGER_CHANNEL,
    disable_idle_timeout: bool = False,
) -> bool:
    cr.execute("SELECT pg_is_in_recovery()")
    recovery = cr.fetchone()
    if recovery and recovery[0]:
        logger.warning("PG cluster in recovery mode, %s trigger not activated", channel)
        return False
    if disable_idle_timeout:
        cr.execute("SET idle_session_timeout = 0")
    cr.execute(SQL("LISTEN %s", SQL.identifier(channel)))
    return True


def drain_cron_notifies(
    connection: typing.Any, *, channel: str = CRON_TRIGGER_CHANNEL
) -> OrderedSet:
    return OrderedSet(
        notif.payload
        for notif in connection.notifies(timeout=0)
        if notif.channel == channel
    )


def order_notified_first(notified: Iterable[str], all_dbs: Iterable[str]) -> list[str]:
    if isinstance(notified, Iterator):
        notified = list(notified)
    all_list = list(all_dbs)
    all_set = set(all_list)
    notified_set = set(notified)
    emitted: set[str] = set()
    result: list[str] = []
    for name in notified:
        if name in all_set and name not in emitted:
            emitted.add(name)
            result.append(name)
    for name in all_list:
        if name not in notified_set and name not in emitted:
            emitted.add(name)
            result.append(name)
    return result


_HOST_PLACEHOLDER_RE = re.compile(r"%[hd]")

_dbfilter_warned = False


def _static_dbfilter() -> re.Pattern[str] | None:
    global _dbfilter_warned  # noqa: PLW0603  warn once per process, not per sweep

    pattern = config["dbfilter"]
    if not pattern:
        return None
    if _HOST_PLACEHOLDER_RE.search(pattern):
        if not _dbfilter_warned:
            _dbfilter_warned = True
            _logger.warning(
                "dbfilter %r resolves against the request host (%%h/%%d), so it "
                "cannot scope cron and job polling: those run with no request. "
                "This process will poll every database its role owns. Set "
                "db_name to name the databases it serves, or write a dbfilter "
                "with no host placeholder.",
                pattern,
            )
        return None
    try:
        return re.compile(pattern)
    except re.error:
        _logger.warning(
            "dbfilter %r is not a valid regular expression; not scoping cron "
            "and job polling with it",
            pattern,
            exc_info=True,
        )
        return None


def get_cron_databases() -> list[str]:
    names = config["db_name"]
    if names:
        return list(names)
    names = [name for name in list_dbs(True) if not is_maintenance_db(name)]
    dbfilter = _static_dbfilter()
    if dbfilter is None:
        return names
    return [name for name in names if dbfilter.match(name)]


def drain_swept_database(db_name: str) -> None:
    db.drain_db(db_name)


def _get_databases_to_sweep() -> list[str]:
    return get_cron_databases()


def close_cron_cursor(cursor: BaseCursor) -> None:
    with contextlib.suppress(Exception):
        cursor.close()


def open_cron_listener(channel: str, logger: logging.Logger) -> BaseCursor:
    cursor = db.db_connect("postgres").cursor()
    try:
        arm_cron_listen(cursor, logger, channel=channel, disable_idle_timeout=True)
        cursor.commit()
    except BaseException:
        close_cron_cursor(cursor)
        raise
    return cursor


class ReconnectBackoff:
    def __init__(
        self, logger: logging.Logger, *, ceiling: int = BACKOFF_CEILING_S
    ) -> None:
        # Rejected here rather than by backoff.bound on the first failure: a
        # ceiling under the base is a wiring mistake, and the retry path is the
        # worst place to discover one.
        if ceiling < BACKOFF_BASE_S:
            raise ValueError(
                f"ceiling ({ceiling}) is below the {BACKOFF_BASE_S}s base, "
                f"which flattens the reconnect curve"
            )
        self._logger = logger
        self._ceiling = ceiling
        self.attempts = 0

    def reset(self) -> None:
        self.attempts = 0

    def wait_after_failure(
        self,
        what: str,
        exc: BaseException,
        sleep: typing.Callable[[float], None] | None = None,
    ) -> None:
        self.attempts += 1
        delay = backoff.bound(self.attempts, base=BACKOFF_BASE_S, cap=self._ceiling)
        self._logger.warning(
            "%s failed (attempt %d): %s; retrying in %ds",
            what,
            self.attempts,
            exc,
            delay,
        )
        (sleep or time.sleep)(delay)


class CronSchedule:
    def __init__(
        self,
        list_databases: typing.Callable[[], typing.Iterable[str]] | None = None,
        *,
        refresh_interval: float = CRON_POLL_INTERVAL_S,
        clock: typing.Callable[[], float] | None = None,
    ) -> None:
        self._list_databases = list_databases or _get_databases_to_sweep
        self._refresh_interval = refresh_interval
        self._clock = clock or time.monotonic
        self._known: OrderedSet[str] = OrderedSet()
        self._listed_at = float("-inf")

    @property
    def known(self) -> OrderedSet[str]:
        return self._known

    def _is_stale(self) -> bool:
        return self._clock() - self._listed_at >= self._refresh_interval

    def reset_known_databases(self) -> OrderedSet[str]:
        self._known = OrderedSet(self._list_databases())
        self._listed_at = self._clock()
        return self._known

    def get_due_databases(self, notified: Iterable[str]) -> list[str]:
        if self._is_stale():
            return order_notified_first(notified, self.reset_known_databases())
        return [name for name in notified if name in self._known]
