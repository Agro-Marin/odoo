"""Process-control and cron helpers shared by the server and worker modules.

A leaf module (``_worker → _helpers → db``) so those modules can share these
names without an import cycle.  Private: import directly from
``odoo.service._helpers``.
"""

from __future__ import annotations

import os
from typing import Any

from odoo.tools import config

from .db import list_dbs

# Cron and HTTP-worker main loops sleep this long between cycles when no signal
# or NOTIFY is pending.  60 s balances drift responsiveness against idle CPU.
SLEEP_INTERVAL = 60  # 1 min

# Max random sleep after a cron worker wakes on a ``cron_trigger`` NOTIFY, so
# concurrent workers don't all hit PG at once (thundering herd).  Shared by both
# cron paths (``ThreadedServer.cron_thread`` / ``WorkerCron.sleep``).
CRON_NOTIFY_JITTER_MAX_S = 0.1


def memory_info(process: Any) -> int:
    """Return the process's resident memory (RSS) in bytes.

    RSS, not VMS: on Python 3.13+ the allocator and GC reserve large virtual
    ranges that never become resident, so VMS over-reports.  This feeds a soft
    limit for orderly worker recycling; the hard cap belongs to a cgroup v2
    limit on the systemd unit (``MemoryMax=`` + ``MemorySwapMax=0``), not an
    in-process ``RLIMIT_AS`` (which would deny ``pthread_create`` on healthy
    workers given all that never-resident virtual space).
    """
    return process.memory_info().rss


def over_memory_soft_limit(process: Any, soft_limit: int) -> int | None:
    """Return the current RSS when it exceeds ``soft_limit``, else ``None``.

    Shared soft-limit decision for ``Worker.check_limits``,
    ``ThreadedServer.process_limit`` and ``EventServer.process_limits``; each
    caller takes its own recycle action.  ``soft_limit`` of 0 disables the check
    and skips the ``/proc`` RSS read.
    """
    if not soft_limit:
        return None
    memory = memory_info(process)
    return memory if memory > soft_limit else None


def empty_pipe(fd: int) -> None:
    """Drain all pending data from a non-blocking pipe file descriptor.

    Reads in 4 KiB blocks so a backlog drains in few syscalls (in practice the
    backlog is tiny — the prefork signal handler dedups to one pending slot).
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
    "over_memory_soft_limit",
)
