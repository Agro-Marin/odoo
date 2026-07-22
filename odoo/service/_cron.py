"""Shared LISTEN/NOTIFY mechanics for the cron and job-queue drivers.

The threaded (``ThreadedServer.cron_thread`` / ``job_thread``) and prefork
(``WorkerCron`` / ``WorkerJob``) drivers keep different scheduling shapes but
share the wire-level mechanics, kept here as one source of truth:

* arm ``LISTEN <channel>`` unless the cluster is a read replica,
* drain the pending NOTIFYs of that channel without blocking,
* order notified databases ahead of the rest for the next pass.

Depends only on ``odoo.tools`` — no cycle with ``server`` / ``_worker``.
"""

from __future__ import annotations

import typing

from odoo.tools import OrderedSet

if typing.TYPE_CHECKING:
    import logging
    from collections.abc import Iterable

    from odoo.db import BaseCursor

# The LISTEN/NOTIFY channels.  Defined once so publishers (``ir.cron`` /
# ``ir.job``) and consumers cannot drift on the channel names.
CRON_TRIGGER_CHANNEL = "cron_trigger"
JOB_QUEUE_CHANNEL = "job_queue"


def arm_cron_listen(
    cr: BaseCursor,
    logger: logging.Logger,
    *,
    channel: str = CRON_TRIGGER_CHANNEL,
    disable_idle_timeout: bool = False,
) -> bool:
    """Arm ``LISTEN <channel>`` on ``cr`` unless PG is in recovery.

    Returns ``True`` if armed, ``False`` if skipped because the cluster is a hot
    standby (LISTEN/NOTIFY does not work in recovery — the driver falls back to
    its periodic full scan).  The caller commits.

    ``disable_idle_timeout=True`` issues ``SET idle_session_timeout = 0`` first,
    for ``WorkerCron`` / ``WorkerJob`` whose dedicated connection sits idle
    waiting for a NOTIFY and must survive PG 18's idle-session reaper.  The
    threaded drivers recycle on an age limit instead, so they leave it untouched.
    """
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
    """Return de-duplicated payloads of the pending NOTIFYs of ``channel``.

    ``notifies(timeout=0)`` is non-blocking; the channel filter guards against
    another LISTENer sharing the connection.  Ordered + de-duped so a burst of
    NOTIFYs for one database collapses to a single first-seen queue entry.
    """
    return OrderedSet(
        notif.payload
        for notif in connection.notifies(timeout=0)
        if notif.channel == channel
    )


def order_notified_first(notified: Iterable[str], all_dbs: Iterable[str]) -> list[str]:
    """Order ``all_dbs`` so notified databases come first, preserving order.

    Each served database appears exactly once: notified-and-served first (in
    notified order), then the remaining served databases (in original order).
    Notified databases not served by this instance are dropped (a stray NOTIFY
    cannot inject work for an unknown DB).

    De-duplicates both inputs by first occurrence, so a database listed twice —
    whether in ``notified`` or ``all_dbs`` — is still processed only once per
    cron pass.  Today's callers pass de-duplicated ``OrderedSet``s, so this is a
    correct-by-construction guard, not a behavior change for them.
    """
    all_list = list(all_dbs)
    all_set = set(all_list)
    notified_set = set(notified)
    emitted: set[str] = set()
    result: list[str] = []
    for db in notified:  # notified-and-served, notified order, de-duplicated
        if db in all_set and db not in emitted:
            emitted.add(db)
            result.append(db)
    for db in all_list:  # remaining served dbs, original order, de-duplicated
        if db not in notified_set and db not in emitted:
            emitted.add(db)
            result.append(db)
    return result
