"""Per-cursor SQL metrics and debug-stats accounting for :class:`~odoo.db.cursor.Cursor`.

Split out of :mod:`odoo.db.cursor` so the transaction surface stays focused.
``_MetricsMixin`` is mixed into :class:`Cursor` and operates on the host's own
``_thread`` / ``sql_*_log`` / ``sql_log_count`` members (declared below under
``TYPE_CHECKING``); it has no ``__init__``, relying on the host to seed them.

The process-global :data:`sql_counter` lives here and is exposed as
``odoo.db.sql_counter`` via ``odoo/db/__init__.py``'s module ``__getattr__``.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from odoo.tools import SQL

from .errors import CURSOR_LOGGER_NAME

_logger = logging.getLogger(CURSOR_LOGGER_NAME)

# Global SQL query counter (debug/profiling).  A bare, non-atomic int:
# approximate by design, since a process-wide lock on every query would
# serialise all completions (a scalability bottleneck, worst on free-threaded
# builds).  Accuracy by mode:
#   * forked workers (--workers=N): own counter per process — exact.
#   * threaded under the GIL (--workers=0): the GIL serialises `+=`, loss ~0%.
#   * free-threaded (PYTHON_GIL=0): `+=` races and loses most concurrent
#     increments (~93% with 24 threads).  Don't rely on it there; use the
#     thread's own `query_count` (bumped below, no cross-thread contention).
sql_counter: int = 0


if TYPE_CHECKING:
    import threading
    from typing import Protocol

    class _MetricsHost(Protocol):
        """The host-cursor surface that :class:`_MetricsMixin` relies on.

        Mirrors :class:`odoo.db.bulk._CursorInternals`: each method annotates
        ``self`` with this Protocol so its body type-checks against exactly the
        members the host provides.
        """

        _thread: threading.Thread
        sql_from_log: dict[str, tuple[int, float]]
        sql_into_log: dict[str, tuple[int, float]]
        sql_log_count: int


class _MetricsMixin:
    """Query-counter, thread-metric and debug-stats bookkeeping for :class:`Cursor`.

    Stateless (no ``__init__``): operates on the log dicts the host seeds and the
    process-global :data:`sql_counter`.  Stateful methods annotate ``self`` with
    :class:`_MetricsHost`, as in :mod:`odoo.db.bulk`.
    """

    def _format(self, query: Any, params: Any = None) -> str:
        """Format a query for debug logging (approximate, not for execution)."""
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
        """Update query counters, thread-local metrics, and run query hooks.

        Centralises all post-execution bookkeeping so that execute(),
        executemany() and copy_from() share one code path.

        :param query: The executed query (passed to hooks, may be None)
        :param params: The query parameters (passed to hooks, may be None)
        :param start: Monotonic timestamp before execution (passed to hooks)
        :param hooks: the thread's ``query_hooks`` (or None).  Passed in rather
            than re-read here: the caller already read it to gate ``start``, and
            this runs on every query.
        """
        global sql_counter  # noqa: PLW0603 — intentionally process-global
        self.sql_log_count += count
        sql_counter += count
        # hasattr() below isn't worth replacing with try/except (~50ns vs the
        # 1-5ms query time); keep the explicit style.
        t = self._thread
        if hasattr(t, "query_count"):
            t.query_count += count
        if hasattr(t, "query_time"):
            t.query_time += delay
        for hook in hooks or ():
            hook(self, query, params, start, delay)

    def _record_sql_log(
        self: _MetricsHost, query_type: str, table: str | None, delay: float
    ) -> None:
        """Accumulate per-table from/into timing stats (DEBUG-only).

        Shared by :meth:`Cursor.execute` and :meth:`Cursor.copy_from`, whose stats
        bookkeeping was otherwise hand-inlined in two places.  Callers gate on
        ``isEnabledFor(DEBUG)`` so the table extraction cost is only paid when
        the stats will actually be printed.

        :param query_type: ``'into'``, ``'from'`` or ``'other'``.
        :param table: table name, or ``None`` for unclassified queries.
        :param delay: query wall time in seconds.
        """
        if query_type == "into":
            log_target = self.sql_into_log
        elif query_type == "from":
            log_target = self.sql_from_log
        else:
            return
        stat_count, stat_time = log_target.get(table or "", (0, 0))
        log_target[table or ""] = (stat_count + 1, stat_time + delay * 1e6)

    def print_log(self: _MetricsHost) -> None:
        if not _logger.isEnabledFor(logging.DEBUG):
            return

        def process(log_type: str) -> None:
            sqllogs = {"from": self.sql_from_log, "into": self.sql_into_log}
            sqllog = sqllogs[log_type]
            total = 0.0
            if sqllog:
                _logger.debug("SQL LOG %s:", log_type)
                # Sort by accumulated time, slowest first — the costliest tables
                # are what this debug log exists to surface.
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
