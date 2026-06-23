"""Process-control and cron helpers shared by ``server.py`` and ``_worker.py``.

Extracted to break the circular import between those two modules.  The
prior shape was ``server.py → _worker.py → server.py`` (workers needed
``memory_info`` / ``empty_pipe`` / ``cron_database_list`` /
``SLEEP_INTERVAL`` / ``CRON_NOTIFY_JITTER_MAX_S``,
but those helpers lived above the ``from ._worker import ...`` line in
``server.py`` and the partial-module-load was load-bearing).  Moving
them here makes ``_worker.py``'s imports flow strictly downward
(``_worker → _helpers → db``) instead of looping back through
``server``.

Module is ``_helpers`` (leading underscore) to signal "internal" — every
external caller continues to import these names from
``odoo.service.server`` via the re-export shim there.
"""

from __future__ import annotations

import os
from typing import Any

from odoo.tools import config

from .db import list_dbs

# Cron and HTTP-worker main loops sleep for SLEEP_INTERVAL between
# cycles when there is no signal or NOTIFY pending.  60 s is a balance
# between responsiveness to drift (cron jobs whose ``interval_minutes``
# > 1 still fire promptly) and idle CPU on a mostly-quiet instance.
SLEEP_INTERVAL = 60  # 1 min

# Maximum random sleep injected after a cron worker wakes from a
# ``cron_trigger`` NOTIFY.  Spreads concurrent workers reacting to the
# same notify so they don't all hit PG in the same millisecond
# (thundering herd).  The two cron paths
# (``ThreadedServer.cron_thread`` for dev/threaded mode and
# ``WorkerCron.sleep`` for prefork production) used to disagree on the
# value (0.04 s vs 0.1 s) — independently audited and independently
# patched.  Unified here so a future tweak lands in both paths at once.
CRON_NOTIFY_JITTER_MAX_S = 0.1


def memory_info(process: Any) -> int:
    """Return the resident memory (RSS) of the process in bytes.

    VMS (virtual memory size) is unreliable on modern Python (3.13+):
    the new allocator and GC reserve large virtual address ranges that
    never become resident.  RSS reflects actual physical memory
    pressure and is the right metric on every platform.

    This soft limit only flags a worker for orderly recycling.  The hard
    memory cap is enforced externally — the recommended backstop is a
    cgroup v2 limit on the ``odoo.service`` systemd unit (``MemoryMax=`` +
    ``MemorySwapMax=0``).  An in-process ``RLIMIT_AS`` cap is deliberately
    not used: the allocator/gevent reserve multi-GB of virtual space that
    never becomes resident, so the cap denied ``pthread_create`` on healthy
    workers long before any real memory pressure.
    """
    return process.memory_info().rss


def empty_pipe(fd: int) -> None:
    """Drain all data from a non-blocking pipe file descriptor.

    Reads in 4 KiB blocks rather than one byte at a time: a wakeup
    pipe with N bytes pending used to require N syscalls to drain.
    Realistic N is small (<= 5, the signal-queue cap) but the block
    read costs nothing extra and future-proofs against a busier pipe.
    """
    try:
        while os.read(fd, 4096):
            pass
    except BlockingIOError:
        pass


def cron_database_list() -> list[str]:
    """Return the list of databases to consider for cron processing."""
    return config["db_name"] or list_dbs(True)


__all__ = (
    "CRON_NOTIFY_JITTER_MAX_S",
    "SLEEP_INTERVAL",
    "cron_database_list",
    "empty_pipe",
    "memory_info",
)
