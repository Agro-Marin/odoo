from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from odoo.tools import SQL

from .errors import CURSOR_LOGGER_NAME

_logger = logging.getLogger(CURSOR_LOGGER_NAME)

sql_counter: int = 0
"""Process-wide statements-on-the-wire count, deliberately without a lock.

It is the one counter in this package that does not own one, and that is a
decision rather than an oversight -- `PoolStats` owns its lock because
`x += 1` is a read-modify-write, and the same argument would put one here.
Both halves were measured before declining:

- **It loses nothing on this interpreter.** 12 threads x 80 000 increments at
  `setswitchinterval(1e-9)` lost 0. The method is not blind: the same harness
  run against a deliberately non-atomic `read; call; write` lost 774 303 of
  960 000. `LOAD_GLOBAL / BINARY_OP / STORE_GLOBAL` carries no eval-breaker
  check, so CPython 3.14's GIL does not preempt inside it.
- **The lock costs 68.6 ns per statement**, against 157.1 ns for the whole of
  `_record_metrics` -- +44% on the hottest path in the framework, for a race
  that cannot fire.

What makes it wrong is a **free-threaded build**: there the sequence is a real
race and this counter is what `modules/loading.py`, `service/lifecycle.py` and
`tests/result.py` report as "queries". Re-measure here before enabling one; the
fix at that point is not necessarily a lock, since per-thread accumulation
summed on read would keep the write path free.
"""


if TYPE_CHECKING:
    import threading
    from typing import Protocol

    class _MetricsHost(Protocol):
        _thread: threading.Thread

        sql_log_count: int


class _MetricsMixin:
    sql_from_log: dict[str, tuple[int, float]]
    sql_into_log: dict[str, tuple[int, float]]
    sql_log_count: int

    def _init_metrics_state(self) -> None:
        self.sql_from_log = {}
        self.sql_into_log = {}
        self.sql_log_count = 0

    def _format_statement(self, query: Any, params: Any = None) -> str:
        if isinstance(query, SQL):
            query, params = query.code, query.params
        if params is None:
            return str(query)
        try:
            if isinstance(params, dict):
                return str(query) % {k: repr(v) for k, v in params.items()}
            return str(query) % tuple(repr(v) for v in params)
        except Exception:
            return f"{query} [{params!r}]"

    def _record_metrics(
        self: _MetricsHost,
        delay: float,
        count: int = 1,
        *,
        query: Any = None,
        params: Any = None,
        start: float = 0.0,
        hooks: Any = None,
    ) -> None:
        global sql_counter  # noqa: PLW0603  process-wide SQL counter; the module IS the accumulator
        self.sql_log_count += count
        sql_counter += count
        t = self._thread
        if hasattr(t, "query_count"):
            t.query_count += count
        if hasattr(t, "query_time"):
            t.query_time += delay
        for hook in hooks or ():
            hook(self, query, params, start, delay)

    def _record_sql_log(self, query_type: str, table: str | None, delay: float) -> None:
        if query_type == "into":
            log_target = self.sql_into_log
        elif query_type == "from":
            log_target = self.sql_from_log
        else:
            return
        stat_count, stat_time = log_target.get(table or "", (0, 0))
        log_target[table or ""] = (stat_count + 1, stat_time + delay * 1e6)

    def print_log(self) -> None:
        if not _logger.isEnabledFor(logging.DEBUG):
            return

        def print_direction_log(log_type: str) -> None:
            sqllogs = {"from": self.sql_from_log, "into": self.sql_into_log}
            sqllog = sqllogs[log_type]
            total = 0.0
            if sqllog:
                _logger.debug("SQL LOG %s:", log_type)
                for table, (stat_count, stat_time) in sorted(
                    sqllog.items(), key=lambda kv: kv[1][1], reverse=True
                ):
                    delay = timedelta(microseconds=stat_time)
                    _logger.debug("table: %s: %s/%s", table, delay, stat_count)
                    total += stat_time
                sqllog.clear()
            total_delay = timedelta(microseconds=total)
            _logger.debug(
                "SUM %s:%s/%d [%d]",
                log_type,
                total_delay,
                self.sql_log_count,
                sql_counter,
            )

        print_direction_log("from")
        print_direction_log("into")
        self.sql_log_count = 0
