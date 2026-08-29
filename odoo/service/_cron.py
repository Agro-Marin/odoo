from __future__ import annotations

import time
import typing
from collections.abc import Iterable, Iterator

from odoo.tools import SQL, OrderedSet
from odoo.tools.constants import CRON_TRIGGER_CHANNEL, JOB_QUEUE_CHANNEL

if typing.TYPE_CHECKING:
    import logging

    from odoo.db import BaseCursor

__all__ = [
    "CRON_TRIGGER_CHANNEL",
    "JOB_QUEUE_CHANNEL",
    "CronSchedule",
    "arm_cron_listen",
    "drain_cron_notifies",
    "order_notified_first",
]


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
    for db in notified:
        if db in all_set and db not in emitted:
            emitted.add(db)
            result.append(db)
    for db in all_list:
        if db not in notified_set and db not in emitted:
            emitted.add(db)
            result.append(db)
    return result


class CronSchedule:
    """Which databases are due this pass, and when to re-read the list.

    Both cron loops -- the thread in `_threaded` and the process in `_worker` --
    had their own copy of this, and the copies had drifted: the thread re-listed
    at most every `SLEEP_INTERVAL` and intersected the notifies against its
    cached list in between, while the worker re-listed on every wakeup with an
    empty queue.  That is one `pg_database` scan per notify against one per
    minute, for the same job, and nobody decided it.  The answer lives here now,
    so there is one of it.

    `list_databases` is injected rather than imported so this stays testable
    without a catalogue, and so the caller decides what "the databases I serve"
    means.
    """

    def __init__(
        self,
        list_databases: typing.Callable[[], typing.Iterable[str]],
        *,
        refresh_interval: float,
        clock: typing.Callable[[], float] | None = None,
    ) -> None:
        self._list_databases = list_databases
        self._refresh_interval = refresh_interval
        self._clock = clock or time.monotonic
        self._known: OrderedSet[str] = OrderedSet()
        self._listed_at = float("-inf")

    @property
    def known(self) -> OrderedSet[str]:
        return self._known

    def _stale(self) -> bool:
        return self._clock() - self._listed_at >= self._refresh_interval

    def refresh(self) -> OrderedSet[str]:
        self._known = OrderedSet(self._list_databases())
        self._listed_at = self._clock()
        return self._known

    def due(self, notified: Iterable[str]) -> list[str]:
        """Databases to process now, notified ones first.

        A stale list is re-read and every database is due -- that is the
        periodic sweep.  A fresh one answers only the notified databases it
        knows about, so a notify storm cannot turn into a scan storm.
        """
        if self._stale():
            return order_notified_first(notified, self.refresh())
        return [name for name in notified if name in self._known]
