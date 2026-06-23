"""Shared cron LISTEN/NOTIFY mechanics for the two cron drivers.

``ThreadedServer.cron_thread`` (threaded mode) and ``WorkerCron`` (prefork)
keep deliberately different scheduling shapes but share the wire-level cron
mechanics, kept here as one source of truth:

* arm ``LISTEN cron_trigger`` unless the cluster is a read replica,
* drain the pending ``cron_trigger`` NOTIFYs without blocking,
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

# The single LISTEN/NOTIFY channel cron uses.  Defined once so the publisher
# (``ir.cron``) and both consumers cannot drift on the channel name.
CRON_TRIGGER_CHANNEL = "cron_trigger"


def arm_cron_listen(
    cr: BaseCursor,
    logger: logging.Logger,
    *,
    disable_idle_timeout: bool = False,
) -> bool:
    """Arm ``LISTEN cron_trigger`` on ``cr`` unless PG is in recovery.

    Returns ``True`` if LISTEN was armed, ``False`` if skipped because the
    cluster is a hot standby (LISTEN/NOTIFY does not work in recovery mode —
    the driver falls back to its periodic full scan).  The caller commits.

    ``disable_idle_timeout=True`` issues ``SET idle_session_timeout = 0``
    before LISTEN — used by ``WorkerCron`` whose dedicated connection sits
    idle by design waiting for a NOTIFY and must not be reaped by PG 18's
    default idle-session timeout.  The threaded driver recycles its
    connection on an age limit instead, so it leaves the timeout untouched.
    """
    cr.execute("SELECT pg_is_in_recovery()")
    if cr.fetchone()[0]:
        logger.warning("PG cluster in recovery mode, cron trigger not activated")
        return False
    if disable_idle_timeout:
        cr.execute("SET idle_session_timeout = 0")
    cr.execute(f"LISTEN {CRON_TRIGGER_CHANNEL}")
    return True


def drain_cron_notifies(connection: typing.Any) -> OrderedSet:
    """Return de-duplicated payloads of the pending ``cron_trigger`` NOTIFYs.

    ``notifies(timeout=0)`` is non-blocking.  Filtering by channel guards
    against any other LISTENer sharing the connection.  Ordered + de-duped so
    a burst of NOTIFYs for the same database collapses to one queue entry
    while preserving first-seen order.
    """
    return OrderedSet(
        notif.payload
        for notif in connection.notifies(timeout=0)
        if notif.channel == CRON_TRIGGER_CHANNEL
    )


def order_notified_first(
    notified: Iterable[str], all_dbs: Iterable[str]
) -> list[str]:
    """Order ``all_dbs`` so notified databases come first, preserving order.

    Databases that were notified but are not served by this instance are
    dropped (a stray NOTIFY cannot inject work for an unknown DB); databases
    served but not notified follow in their original order.
    """
    all_list = list(all_dbs)
    all_set = set(all_list)
    notified_set = set(notified)
    return [db for db in notified if db in all_set] + [
        db for db in all_list if db not in notified_set
    ]
