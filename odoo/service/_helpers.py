from __future__ import annotations

import logging
import os
import re
from typing import Any

from odoo.db import is_maintenance_db
from odoo.tools import config

from .db import list_dbs

_logger = logging.getLogger("odoo.service.server")

SLEEP_INTERVAL = 60

CRON_NOTIFY_JITTER_MAX_S = 0.1


_MAX_BACKOFF_EXPONENT = 30


def capped_backoff(attempts: int, ceiling: int = SLEEP_INTERVAL) -> int:
    return min(2 ** min(attempts, _MAX_BACKOFF_EXPONENT), ceiling)


INHERIT_FROM_CRON = -1


def _inherits_from_cron(limit: int) -> bool:
    return limit == INHERIT_FROM_CRON or limit < INHERIT_FROM_CRON


def job_max_age() -> int:
    limit = config["limit_time_worker_job"]
    return config["limit_time_worker_cron"] if _inherits_from_cron(limit) else limit


def _job_real_time_limit() -> int:
    limit = config["limit_time_real_job"]
    return config["limit_time_real_cron"] if _inherits_from_cron(limit) else limit


def cron_real_time_budget() -> float:
    limit = config["limit_time_real_cron"]
    if _inherits_from_cron(limit):
        limit = config["limit_time_real"]
    return max(limit, 0)


def job_real_time_budget() -> float:
    limit = _job_real_time_limit()
    if _inherits_from_cron(limit):
        limit = config["limit_time_real"]
    return max(limit, 0)


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


__all__ = (
    "CRON_NOTIFY_JITTER_MAX_S",
    "INHERIT_FROM_CRON",
    "SLEEP_INTERVAL",
    "capped_backoff",
    "cron_database_list",
    "cron_real_time_budget",
    "empty_pipe",
    "job_max_age",
    "job_real_time_budget",
    "memory_info",
    "over_memory_soft_limit",
)
