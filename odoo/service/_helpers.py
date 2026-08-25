from __future__ import annotations

import os
from typing import Any

from odoo.tools import config

from .db import list_dbs

SLEEP_INTERVAL = 60

CRON_NOTIFY_JITTER_MAX_S = 0.1


#: Exponent ceiling for :func:`capped_backoff`.  ``2 ** 30`` already dwarfs any
#: ``ceiling`` this package passes; the bound exists only to keep an unbounded
#: ``attempts`` from building a bignum on its way to being clamped away.
_MAX_BACKOFF_EXPONENT = 30


def capped_backoff(attempts: int, ceiling: int = SLEEP_INTERVAL) -> int:
    return min(2 ** min(attempts, _MAX_BACKOFF_EXPONENT), ceiling)


#: ``--limit-time-*-job`` sentinel meaning "whatever the cron setting resolved
#: to".  Job workers had no lifetime configuration of their own at all: tuning
#: cron silently retuned jobs, in both server flavours.  The default keeps that
#: behaviour, and the knob now exists for when it is wrong.
INHERIT_FROM_CRON = -1


def job_max_age() -> int:
    """Seconds a job worker/thread may live. 0 disables recycling."""
    limit = config["limit_time_worker_job"]
    return config["limit_time_worker_cron"] if limit < 0 else limit


def job_time_real() -> int:
    """Wall-clock ceiling for one job. 0 disables it, <0 defers to cron."""
    limit = config["limit_time_real_job"]
    return config["limit_time_real_cron"] if limit < 0 else limit


def memory_info(process: Any) -> int:
    return process.memory_info().rss


def over_memory_soft_limit(process: Any, soft_limit: int) -> int | None:
    if not soft_limit:
        return None
    memory = memory_info(process)
    return memory if memory > soft_limit else None


def empty_pipe(fd: int) -> None:
    try:
        while os.read(fd, 4096):
            pass
    except BlockingIOError:
        pass


def cron_database_list() -> list[str]:
    return config["db_name"] or list_dbs(True)


__all__ = (
    "CRON_NOTIFY_JITTER_MAX_S",
    "INHERIT_FROM_CRON",
    "SLEEP_INTERVAL",
    "capped_backoff",
    "cron_database_list",
    "empty_pipe",
    "job_max_age",
    "job_time_real",
    "memory_info",
    "over_memory_soft_limit",
)
