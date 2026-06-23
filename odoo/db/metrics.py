"""Per-cursor SQL metrics and debug-stats accounting for :class:`~odoo.db.cursor.Cursor`.

Split out of :mod:`odoo.db.cursor` — like :mod:`odoo.db.bulk` — so the core
transaction surface stays focused on transaction control.  ``_MetricsMixin`` is
mixed into :class:`Cursor` (``class Cursor(_BulkAccessMixin, _MetricsMixin,
BaseCursor)``) and operates on the host cursor's own ``_thread`` /
``sql_from_log`` / ``sql_into_log`` / ``sql_log_count`` members (declared below
for type checkers under ``TYPE_CHECKING``).  It declares no ``__init__``: the
host's ``__init__`` seeds the log dicts, exactly as the bulk mixin relies on
host-provided ``_obj`` / ``_cnx``.

The process-global :data:`sql_counter` lives here (it was previously a bare
cursor-module global) and is exposed to callers as ``odoo.db.sql_counter`` via
``odoo/db/__init__.py``'s module ``__getattr__``, which reads it from this module.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from odoo.tools import SQL

from .errors import CURSOR_LOGGER_NAME

_logger = logging.getLogger(CURSOR_LOGGER_NAME)

# Global SQL query counter (used for debugging/profiling).
# Intentionally a bare int — not atomic.  Under --workers=0 (threaded),
# concurrent += can lose counts.  This is acceptable: the counter is
# approximate by design and adding a lock would slow every query for
# debug-only data.  In forked mode each worker has its own copy.
sql_counter: int = 0


if TYPE_CHECKING:
    import threading
    from typing import Protocol

    class _MetricsHost(Protocol):
        """The host-cursor surface that :class:`_MetricsMixin` relies on.

        Mirrors :class:`odoo.db.bulk._CursorInternals`: each stateful mixin
        method annotates ``self`` with this Protocol so the bodies type-check
        against exactly the members the host (:class:`~odoo.db.cursor.Cursor`)
        provides, keeping the coupling in one place instead of re-declaring
        Cursor's members on the mixin.
        """

        _thread: threading.Thread
        sql_from_log: dict[str, tuple[int, float]]
        sql_into_log: dict[str, tuple[int, float]]
        sql_log_count: int


class _MetricsMixin:
    """Query-counter, thread-metric and debug-stats bookkeeping for :class:`Cursor`.

    Stateless (no ``__init__``): the methods operate on the log dicts and
    ``sql_log_count`` the host seeds in its own ``__init__``, and on the
    process-global :data:`sql_counter` defined in this module.  The stateful
    methods annotate ``self`` with :class:`_MetricsHost` (a ``TYPE_CHECKING``-only
    Protocol), the canonical mixin pattern also used by :mod:`odoo.db.bulk`.
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
    ) -> None:
        """Update query counters, thread-local metrics, and run query hooks.

        Centralises all post-execution bookkeeping so that execute(),
        executemany() and copy_from() share one code path.

        :param query: The executed query (passed to hooks, may be None)
        :param params: The query parameters (passed to hooks, may be None)
        :param start: Monotonic timestamp before execution (passed to hooks)
        """
        global sql_counter  # noqa: PLW0603 — intentionally process-global
        self.sql_log_count += count
        sql_counter += count
        # NB: hasattr() calls below look like optimization candidates (try/except
        # is faster on the happy path) but the difference is ~50ns/call — irrelevant
        # vs. the ~1-5ms average query time.  Keep the explicit style for clarity.
        t = self._thread
        if hasattr(t, "query_count"):
            t.query_count += count
        if hasattr(t, "query_time"):
            t.query_time += delay
        for hook in getattr(t, "query_hooks", ()):
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
                # are what this debug log exists to surface.  (Previously keyed on
                # the whole ``(count, time)`` tuple, which ordered by count first
                # and buried a single expensive query on a rarely-hit table.)
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
