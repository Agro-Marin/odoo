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

# Cron and HTTP-worker main loops sleep for SLEEP_INTERVAL between
# cycles when there is no signal or NOTIFY pending.  60 s is a balance
# between responsiveness to drift (cron jobs whose ``interval_minutes``
# > 1 still fire promptly) and idle CPU on a mostly-quiet instance.
SLEEP_INTERVAL = 60  # 1 min

# Maximum random sleep injected after a cron worker wakes from a
# ``cron_trigger`` NOTIFY, so concurrent workers don't all hit PG in the same
# millisecond (thundering herd).  Shared by both cron paths
# (``ThreadedServer.cron_thread`` and ``WorkerCron.sleep``) to keep them in sync.
CRON_NOTIFY_JITTER_MAX_S = 0.1


def memory_info(process: Any) -> int:
    """Return the resident memory (RSS) of the process in bytes.

    RSS, not VMS: on Python 3.13+ the allocator and GC reserve large virtual
    ranges that never become resident, so VMS over-reports.  RSS reflects
    actual physical pressure on every platform.

    This is only a soft limit that flags a worker for orderly recycling.  The
    hard cap belongs to a cgroup v2 limit on the systemd unit (``MemoryMax=`` +
    ``MemorySwapMax=0``); an in-process ``RLIMIT_AS`` is avoided because the
    allocator/gevent reserve multi-GB of never-resident virtual space, so the
    cap would deny ``pthread_create`` on healthy workers.
    """
    return process.memory_info().rss


def over_memory_soft_limit(process: Any, soft_limit: int) -> int | None:
    """Return the current RSS when it exceeds ``soft_limit``, else ``None``.

    The single soft-memory-limit decision shared by ``Worker.check_limits``,
    ``ThreadedServer.process_limit`` and ``EventServer.process_limits``; each
    caller then takes its own recycle action (flag the worker for orderly exit,
    mark the over-limit thread, or ``SIGTERM`` the process) and logs at its own
    level.  A ``soft_limit`` of 0 disables the check (gunicorn ``max_requests``
    semantics); the ``/proc`` RSS read is skipped in that case rather than read
    and discarded.
    """
    if not soft_limit:
        return None
    memory = memory_info(process)
    return memory if memory > soft_limit else None


def empty_pipe(fd: int) -> None:
    """Drain all pending data from a non-blocking pipe file descriptor.

    Reads in 4 KiB blocks so an N-byte backlog drains in one syscall instead of
    N (realistic N is small — the signal-queue cap is 5 — but blocks cost
    nothing extra).
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
