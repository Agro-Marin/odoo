from __future__ import annotations

import typing
from collections.abc import Iterator

from odoo.libs.constants import CRON_TRIGGER_CHANNEL, JOB_QUEUE_CHANNEL
from odoo.tools import OrderedSet

if typing.TYPE_CHECKING:
    import logging
    from collections.abc import Iterable

    from odoo.db import BaseCursor

__all__ = [
    "CRON_TRIGGER_CHANNEL",
    "JOB_QUEUE_CHANNEL",
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
    if cr.fetchone()[0]:
        logger.warning("PG cluster in recovery mode, %s trigger not activated", channel)
        return False
    if disable_idle_timeout:
        cr.execute("SET idle_session_timeout = 0")
    cr.execute(f"LISTEN {channel}")
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
