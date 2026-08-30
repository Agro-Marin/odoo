"""Time, memory and back-off budgets: what bounds a worker, and the arithmetic.

Named for what is left after the cron sweep moved to `_cron`.  As `_helpers` it
was seven unrelated subjects -- backoff, config budgets, RSS accounting, pipe
draining, dbfilter compilation, the cron database list and pool draining -- and
a module named for being a module attracts the next one.

`empty_pipe` is the one resident that is not a budget.  Both the prefork master
and its workers drain their own wake-up pipes, so it needs a home neither owns,
and a module of its own for one four-line function is not one.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from odoo.tools import config

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
    """Walk a fallback chain of config keys, most specific first.

    Every budget below is "use my own key, unless it asks to inherit, in which
    case use the next one out".  Four functions each spelled that walk by hand,
    and `job_real_time_budget` reached its third level only by re-testing the
    sentinel on the *result* of a helper -- which works, but hides the chain in
    the call graph instead of stating it.  Spelled as a key list, the chains
    line up and their one asymmetry is legible:

        limit_time_worker_job -> limit_time_worker_cron
        limit_time_real_cron  -> limit_time_real
        limit_time_real_job   -> limit_time_real_cron -> limit_time_real

    `job_max_age` is the two-level one: a worker job's max AGE does not fall
    back to `limit_time_real` the way its real-time BUDGET does.  Behaviour is
    unchanged from when that was four separate functions; it is written down
    here so the next reader can decide whether it was meant.

    The last key is the end of the chain: if it too asks to inherit, its value
    is returned as-is and the caller's own clamp applies.
    """
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
