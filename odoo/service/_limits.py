from __future__ import annotations

import logging
import os
from typing import Any

from odoo.tools.config import config

_logger = logging.getLogger("odoo.service.server")

BACKOFF_CEILING_S = 60
"""Longest a reconnect back-off will wait.

Its own constant.  It was `SLEEP_INTERVAL`, the cron poll interval, which three
unrelated things had borrowed for the number 60 rather than the meaning: this
ceiling, the cron sweep cadence, and how long `ThreadedServer.run` lets
in-flight requests finish before reloading.  Tuning any one of them moved the
other two.
"""

_MAX_BACKOFF_EXPONENT = 30


def capped_backoff(attempts: int, ceiling: int = BACKOFF_CEILING_S) -> int:
    return min(2 ** min(attempts, _MAX_BACKOFF_EXPONENT), ceiling)


INHERIT_FROM_CRON = -1


def _inherits_from_cron(limit: int) -> bool:
    return limit <= INHERIT_FROM_CRON


def _resolve_budget(*keys: str) -> int:
    limit = config[keys[0]]
    for key in keys[1:]:
        if not _inherits_from_cron(limit):
            break
        limit = config[key]
    return limit


def job_max_age() -> int:
    return _resolve_budget("limit_time_worker_job", "limit_time_worker_cron")


def cron_real_time_budget() -> float:
    return max(_resolve_budget("limit_time_real_cron", "limit_time_real"), 0)


def job_real_time_budget() -> float:
    return max(
        _resolve_budget(
            "limit_time_real_job", "limit_time_real_cron", "limit_time_real"
        ),
        0,
    )


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


__all__ = (
    "BACKOFF_CEILING_S",
    "INHERIT_FROM_CRON",
    "capped_backoff",
    "cron_real_time_budget",
    "empty_pipe",
    "job_max_age",
    "job_real_time_budget",
    "memory_info",
    "over_memory_soft_limit",
)
