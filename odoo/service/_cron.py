"""Everything both cron loops agree on: the channel, the schedule, the sweep.

**Where the patch seam is.**  A name defined here is reached in one of two
ways, and which one decides where a test patches it:

  - Called from inside this module -- `cron_database_list` (through
    `CronSchedule`), `arm_cron_listen` and `db` (through `open_cron_listener`),
    `capped_backoff` (through `ReconnectBackoff`).  One seam, here:
    `odoo.service._cron.<name>`.
  - `from ._cron import ...`-ed and called by `_threaded` or `_worker` --
    `drain_cron_notifies`, `release_swept_database`.  The binding is in the
    importing module, so the seam is `odoo.service._threaded.<name>` or
    `odoo.service._worker.<name>`, one per loop.

`cron_database_list` used to be in the second group, which is why each loop
carried a byte-identical `_databases_to_sweep` wrapper: without one, a test
could patch `_threaded`'s copy and leave `_worker`'s sweeping every database
on the box.  Moving it behind `CronSchedule`'s default put it in the first
group and deleted both wrappers.
"""

from __future__ import annotations

import contextlib
import logging
import re
import time
import typing
from collections.abc import Iterable, Iterator

from odoo import db
from odoo.db import is_maintenance_db
from odoo.tools import SQL, OrderedSet, config
from odoo.tools.constants import CRON_TRIGGER_CHANNEL, JOB_QUEUE_CHANNEL

from ._limits import BACKOFF_CEILING_S, capped_backoff
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
    "cron_database_list",
    "drain_cron_notifies",
    "open_cron_listener",
    "order_notified_first",
    "release_cron_cursor",
    "release_swept_database",
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


def cron_database_list() -> list[str]:
    names = config["db_name"]
    if names:
        return list(names)
    names = [name for name in list_dbs(True) if not is_maintenance_db(name)]
    dbfilter = _static_dbfilter()
    if dbfilter is None:
        return names
    return [name for name in names if dbfilter.match(name)]


def release_swept_database(db_name: str) -> None:
    """Let go of a database's connections between cron/job sweeps.

    DRAIN, not close.  Draining releases the idle server connections but keeps
    the per-DSN pool object and the record that its DSN is reachable, so the
    next sweep's borrow finds an open pool and returns immediately.  Closing
    discards both -- `close_database` pops the pool AND does
    `_reachable_keys.discard(k)` -- so `_get_or_create_pool` then takes its
    `_probe_connectable_deduped` branch and builds a fresh `_PsycopgPool`
    (`open=True`, `num_workers=3`) for that database.  Per database, per sweep,
    for as long as the process lives.

    The threaded cron loop drained and the prefork cron worker closed.  Same
    guard on both sides (`> 1` database this pass), same intent in both
    comments, two different primitives, and nothing chose that -- the split
    survived the extraction of `CronSchedule`, which unified everything about
    the sweep except its last line.  It is one behaviour, so it is spelled
    once, here.
    """
    db.drain_db(db_name)


def _databases_to_sweep() -> list[str]:
    """Resolve `cron_database_list` through the module, not through a binding.

    `CronSchedule`'s default goes through this so a test patching
    `odoo.service._cron.cron_database_list` reaches every loop, which a
    from-import bound at construction would not.
    """
    return cron_database_list()


def release_cron_cursor(cursor: BaseCursor) -> None:
    """Close the cursor.  Do NOT also close the connection under it.

    `Cursor._close` ends in `pool.give_back(self._cnx, keep_in_pool=...)`, so
    by the time `close()` returns the connection is the pool's business, and
    what the pool does with it depends on the DSN.  Measured both ways:

      - `postgres`, which is what both cron loops connect to, is a maintenance
        database, so `give_back` takes its `_DIRECT_CONNECTION` branch and
        closes the connection itself -- `cursor.connection.closed` is already
        True on return.  A second close there is dead code.
      - a pooled DSN comes back with `closed` False because the pool is
        *holding it open* for the next borrower.  Closing it there destroys a
        live pooled connection and costs whoever gets it a reconnect.

    Dead where it runs and harmful where it does not, so it is not done.  The
    threaded loop had this right all along with `contextlib.closing(cursor)`;
    the prefork worker closed the connection FIRST, which made `_do_rollback`
    fail and the cursor log "Failed to roll back on cursor close; discarding
    connection" at ERROR with a traceback on every clean teardown -- a real
    SIGTERM printed two, one per cron/job worker.  `suppress` hid the
    exception and not the log, which is why it read as safe.
    """
    with contextlib.suppress(Exception):
        cursor.close()


def open_cron_listener(channel: str, logger: logging.Logger) -> BaseCursor:
    """A `postgres` cursor armed to LISTEN on `channel`, or an exception.

    Both loops spelled this out -- connect, cursor, arm, commit -- and released
    the cursor by hand, differently, when the arming failed.
    """
    cursor = db.db_connect("postgres").cursor()
    try:
        arm_cron_listen(cursor, logger, channel=channel, disable_idle_timeout=True)
        cursor.commit()
    except BaseException:
        release_cron_cursor(cursor)
        raise
    return cursor


class ReconnectBackoff:
    """Attempt counting and the capped exponential delay, once.

    The threaded loop counted attempts in a local and slept with `time.sleep`;
    the prefork worker counted them on the instance and slept through
    `_sleep_with_watchdog`, which keeps pinging the master so a long PostgreSQL
    outage is not read as a hung worker.  Same policy, two spellings, and the
    only real difference is which sleep.

    That sleep is an argument to `wait_after`, not to `__init__`, and neither
    is captured anywhere: a callable stored at construction is resolved once,
    so patching `time.sleep` or a worker's `_sleep_with_watchdog` afterwards
    cannot reach it -- and a test that means to fake a 60s back-off then sleeps
    for it.  Both mistakes were made here before this note existed.
    """

    def __init__(
        self, logger: logging.Logger, *, ceiling: int = BACKOFF_CEILING_S
    ) -> None:
        self._logger = logger
        self._ceiling = ceiling
        self.attempts = 0

    def reset(self) -> None:
        self.attempts = 0

    def wait_after(
        self,
        what: str,
        exc: BaseException,
        sleep: typing.Callable[[float], None] | None = None,
    ) -> None:
        self.attempts += 1
        delay = capped_backoff(self.attempts, self._ceiling)
        self._logger.warning(
            "%s failed (attempt %d): %s; retrying in %ds",
            what,
            self.attempts,
            exc,
            delay,
        )
        (sleep or time.sleep)(delay)


class CronSchedule:
    """Which databases are due this pass, and when to re-read the list.

    Both cron loops -- the thread in `_threaded` and the process in `_worker` --
    had their own copy of this, and the copies had drifted: the thread re-listed
    at most every `CRON_POLL_INTERVAL_S` and intersected the notifies against its
    cached list in between, while the worker re-listed on every wakeup with an
    empty queue.  That is one `pg_database` scan per notify against one per
    minute, for the same job, and nobody decided it.  The answer lives here now,
    so there is one of it.

    `list_databases` may be injected so this stays testable without a
    catalogue, and so a caller can decide what "the databases I serve" means.
    Left out, it resolves `cron_database_list` **at call time** through this
    module -- which is what makes one patch seam serve both loops.  Binding the
    function at construction would freeze whatever was there when the worker
    was built, and each loop used to carry its own identical `_databases_to_sweep`
    wrapper to avoid exactly that.  There is one of it now, and it is here,
    beside the sweep it belongs to.
    """

    def __init__(
        self,
        list_databases: typing.Callable[[], typing.Iterable[str]] | None = None,
        *,
        refresh_interval: float = CRON_POLL_INTERVAL_S,
        clock: typing.Callable[[], float] | None = None,
    ) -> None:
        self._list_databases = list_databases or _databases_to_sweep
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
