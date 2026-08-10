from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from odoo.tools import SQL

from .errors import CURSOR_LOGGER_NAME

_logger = logging.getLogger(CURSOR_LOGGER_NAME)

sql_counter: int = 0


if TYPE_CHECKING:
    import threading
    from typing import Protocol

    class _MetricsHost(Protocol):
        """What this mixin needs from its host and does not own.

        It used to list ``sql_from_log`` / ``sql_into_log`` / ``sql_log_count``
        too — the three counters this mixin maintains, declared on ``Cursor``
        and reached back for from here. That is a ``_MetricsMixin -> cursor.py``
        edge, and with ``cursor.py -> _MetricsMixin`` already there it made the
        ``Cursor`` composition a 2-cycle: found on 2026-08-09, the first time
        anything measured it (``mixin_coupling_check``'s fourth composition, and
        the fourth to be worst-in-set when first looked at).

        A Protocol naming what a mixin reaches back for is the same tell as
        ``_RegistryStubs`` was for ``Registry``: state with no owner. The
        counters are *metrics*, so they belong here, and now they are here —
        leaving this Protocol with the one member that genuinely is the host's.
        """

        _thread: threading.Thread


class _MetricsMixin:
    """SQL accounting for a cursor: per-table timings and statement counts."""

    #: Owned and initialised here, not by ``Cursor``. See ``_MetricsHost``.
    sql_from_log: dict[str, tuple[int, float]]
    sql_into_log: dict[str, tuple[int, float]]
    sql_log_count: int

    def _init_metrics_state(self) -> None:
        """Initialise this mixin's own counters. Called by ``Cursor.__init__``."""
        self.sql_from_log = {}
        self.sql_into_log = {}
        self.sql_log_count = 0

    def _format(self, query: Any, params: Any = None) -> str:
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

        def process(log_type: str) -> None:
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

        process("from")
        process("into")
        self.sql_log_count = 0
