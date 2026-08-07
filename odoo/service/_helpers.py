from __future__ import annotations

import os
from typing import Any

from odoo.tools import config

from .db import list_dbs

SLEEP_INTERVAL = 60

CRON_NOTIFY_JITTER_MAX_S = 0.1


def capped_backoff(attempts: int, ceiling: int = SLEEP_INTERVAL) -> int:
    return min(2 ** min(attempts, ceiling.bit_length()), ceiling)


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
    "SLEEP_INTERVAL",
    "capped_backoff",
    "cron_database_list",
    "empty_pipe",
    "memory_info",
    "over_memory_soft_limit",
)
