import logging
import os
import threading
import warnings
from collections.abc import Generator, Iterable
from contextlib import contextmanager, suppress
from datetime import datetime
from inspect import currentframe
from time import monotonic
from typing import TYPE_CHECKING, Any, Self

import psycopg
from psycopg import IsolationLevel
from psycopg import sql as _sql

from odoo import tools
from odoo.libs.func import frame_codeinfo
from odoo.tools import SQL
from odoo.tools.misc import Callbacks, real_time

from .bulk import _BulkAccessMixin
from .ddl import _SCHEMA_CHANGING_DDL, _ddl_keyword, _inline_ddl_params
from .errors import _log_sql_error
from .metrics import _MetricsMixin
from .savepoint import Savepoint, _FlushingSavepoint
from .schema_cache import schema_cache
from .utils import categorize_query

# Rust-accelerated rows→dicts conversion (~2.5x faster than pure Python).
# Falls back to Python list comprehension when odoo_rust is not installed.
try:
    from odoo_rust import rows_to_dicts as _rows_to_dicts
except ImportError:
    _rows_to_dicts = None

from .pool import ConnectionPool

if TYPE_CHECKING:
    from odoo.orm.runtime import Transaction

    # when type checking, the BaseCursor exposes methods of the psycopg cursor
    _CursorProtocol = psycopg.Cursor
else:
    _CursorProtocol = object

_logger = logging.getLogger(__name__)


def _clear_schema_caches(dbname: str | None = None) -> None:
    """Drop cached schema lookups (column types, id sequences).

    Thin delegating wrapper kept as :mod:`odoo.db`'s documented cache-
    invalidation hook (imported by ``odoo/db/__init__.py`` and called from
    ``close_db`` / ``drain_*``).  The state and the race-free clear logic now
    live in :class:`~odoo.db.schema_cache.SchemaCache`.

    :param dbname: only drop entries for this database; ``None`` drops all.
    """
    schema_cache.clear(dbname)


# _CursorProtocol declares the available methods and type information,
# at runtime, it is just an `object`
class BaseCursor(_CursorProtocol):
    """Base class for cursors that manage pre/post commit hooks."""

    BATCH_SIZE = 1000  # max array size per = ANY() query — keeps planner efficient
    _MAX_FLUSH_PASSES = 10  # flush()↔precommit ping-pong budget before giving up

    # Class used by ``savepoint(flush=True)``.  Defaults to the db-layer
    # :class:`_FlushingSavepoint` (flush + savepoint-depth only); the ORM layer
    # overrides it with its cache/env-restoring subclass on import
    # (``odoo.orm.runtime.savepoint``), keeping the db→ORM dependency
    # one-directional.  Safe before the ORM loads: without the ORM no
    # transaction is ever attached, so the base class's no-op restore is exactly
    # correct.
    _flushing_savepoint_cls: type[Savepoint] = _FlushingSavepoint

    transaction: Transaction | None
    cache: dict[Any, Any]
    dbname: str
    # Number of SAVEPOINTs currently open on THIS cursor.  Maintained by
    # ``Savepoint`` (every variant, flushing or not) and read by
    # ``Cursor.commit``/``rollback`` to forbid committing/rolling back the whole
    # transaction while a savepoint is live.  The SINGLE source of truth for the
    # guard — it lives on the cursor (not the ORM ``transaction``) so it protects
    # bare ``db_connect`` cursors (migrations, CLI, ``odoo.service.db``) and
    # ``savepoint(flush=False)`` too, cases an ORM-transaction-scoped counter
    # would miss.
    _savepoint_depth: int

    def __init__(self) -> None:
        self.precommit = Callbacks()
        self.postcommit = Callbacks()
        self.prerollback = Callbacks()
        self.postrollback = Callbacks()
        self._now: datetime | None = None
        self._savepoint_depth = 0
        self.cache = {}
        # By default a cursor has no transaction object.  A transaction object
        # for managing environments is attached lazily on first Environment
        # construction (``Environment.__new__`` sets ``cr.transaction =
        # Transaction(...)`` when it is still None) — NOT by ``registry.cursor()``,
        # which only returns ``self._db.cursor()``.  It is not done here in order
        # to avoid cyclic module dependencies.
        self.transaction = None

    def flush(self) -> None:
        """Flush the current transaction, and run precommit hooks.

        Convergence contract: a precommit hook signals follow-up work by
        dirtying the ORM — which the *next* pass's ``transaction.flush()``
        re-queues — NOT by synchronously re-adding itself to ``self.precommit``.
        ``_MAX_FLUSH_PASSES`` bounds only this cross-pass ping-pong.  A hook that
        re-adds itself is drained inside a single ``Callbacks.run()`` below and
        never reaches the budget, so an *unconditional* self-re-add loops forever
        in ``run()`` instead of raising the non-convergence error.
        """
        # A precommit hook may add another precommit hook or dirty the ORM
        # again, so flush + drain repeats until a pass produces no new work.
        # Bound the passes so a hook that keeps re-triggering changes cannot
        # loop forever.
        for _ in range(self._MAX_FLUSH_PASSES):
            if self.transaction is not None:
                self.transaction.flush()
            if not self.precommit:
                return
            self.precommit.run()
        # One final flush after the last drain.  The loop's convergence check
        # runs *before* each ``run()``, so without this trailing flush the last
        # ``run()``'s effect is never re-examined and a chain that settles on
        # the final pass would raise spuriously (the effective budget would be
        # ``_MAX_FLUSH_PASSES - 1``, not ``_MAX_FLUSH_PASSES``).
        if self.transaction is not None:
            self.transaction.flush()
        if self.precommit:
            # Raise, don't warn: callers (commit()) would otherwise COMMIT
            # and clear() the still-pending precommit hooks — silently
            # dropping whatever work they were supposed to do.
            raise RuntimeError(
                f"flush() did not converge after {self._MAX_FLUSH_PASSES} "
                f"iterations: precommit hooks keep triggering new ORM changes; "
                f"committing now would silently drop pending hooks."
            )

    def clear(self) -> None:
        """Clear the current transaction, and clear precommit hooks."""
        if self.transaction is not None:
            self.transaction.clear()
        self.precommit.clear()

    def reset(self) -> None:
        """Reset the current transaction (this invalidates more that clear()).
        This method should be called only right after commit() or rollback().
        """
        if self.transaction is not None:
            self.transaction.reset()

    def execute(
        self,
        query: str | SQL,
        params: tuple | list | dict | None = None,
        log_exceptions: bool = True,
    ) -> None:
        """Execute a query inside the current transaction."""
        raise NotImplementedError

    def commit(self) -> None:
        """Commit the current transaction."""
        raise NotImplementedError

    def rollback(self) -> None:
        """Rollback the current transaction."""
        raise NotImplementedError

    def savepoint(self, flush: bool = True) -> Savepoint:
        """context manager entering in a new savepoint

        With ``flush`` (the default), will automatically run (or clear) the
        relevant hooks.  The flushing variant is resolved via
        ``_flushing_savepoint_cls`` so the ORM layer can inject its
        cache/env-restoring subclass without the db layer importing it.
        """
        if flush:
            return self._flushing_savepoint_cls(self)
        return Savepoint(self)

    def __enter__(self) -> Self:
        """Using the cursor as a contextmanager automatically commits and
        closes it::

            with cr:
                cr.execute(...)

            # cr is committed if no failure occurred
            # cr is closed in any case
        """
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> None:
        try:
            if exc_type is None:
                self.commit()
        finally:
            self.close()

    def fetchscalar(self) -> Any:
        """Fetch a single scalar value from a single-column query.

        Returns ``None`` if no rows are available.  Eliminates the
        common ``cr.fetchone()[0]`` pattern which raises on empty results.
        """
        # Implemented over self.fetchone() rather than left abstract: a bare
        # ``raise NotImplementedError`` body is found by normal MRO lookup and
        # therefore SHADOWS the __getattr__ delegation that TestCursor relies
        # on.  fetchone() is intentionally NOT declared on the base, so on
        # TestCursor it forwards to the real cursor; fetchscalar would not, and
        # ``test_cursor.fetchscalar()`` would raise NotImplementedError while
        # working in production — a trap for any controller using it under an
        # integration test.  Cursor overrides this for one fewer attribute hop;
        # every other subclass inherits a correct version for free.
        row = self.fetchone()
        return row[0] if row else None

    def dictfetchone(self) -> dict[str, Any] | None:
        """Return the first row as a dict (column_name -> value) or None if no rows are available."""
        raise NotImplementedError

    def dictfetchmany(self, size: int) -> list[dict[str, Any]]:
        res: list[dict[str, Any]] = []
        while size > 0 and (row := self.dictfetchone()) is not None:
            res.append(row)
            size -= 1
        return res

    def dictfetchall(self) -> list[dict[str, Any]]:
        """Return all rows as dicts (column_name -> value)."""
        res: list[dict[str, Any]] = []
        while (row := self.dictfetchone()) is not None:
            res.append(row)
        return res

    def now(self) -> datetime:
        """Return the transaction's timestamp ``NOW() AT TIME ZONE 'UTC'``."""
        if self._now is None:
            self.execute("SELECT (now() AT TIME ZONE 'UTC')")
            row = self.fetchone()
            # Explicit check survives ``python -O`` where ``assert`` is stripped.
            if row is None:
                raise RuntimeError("SELECT now() returned no row — connection broken?")
            self._now = row[0]
        return self._now


class Cursor(_BulkAccessMixin, _MetricsMixin, BaseCursor):
    """Represents an open transaction to the PostgreSQL DB backend,
    acting as a lightweight wrapper around psycopg's
    ``Cursor`` objects (native server-side binding).

     ``Cursor`` is the object behind the ``cr`` variable used all
     over the Odoo code.

     .. rubric:: Transaction Isolation

     One very important property of database transactions is the
     level of isolation between concurrent transactions.
     The SQL standard defines four levels of transaction isolation,
     ranging from the most strict *Serializable* level, to the least
     strict *Read Uncommitted* level. These levels are defined in
     terms of the phenomena that must not occur between concurrent
     transactions, such as *dirty read*, etc.
     In the context of a generic business data management software
     such as Odoo, we need the best guarantees that no data
     corruption can ever be cause by simply running multiple
     transactions in parallel. Therefore, the preferred level would
     be the *serializable* level, which ensures that a set of
     transactions is guaranteed to produce the same effect as
     running them one at a time in some order.

     PostgreSQL implements ``REPEATABLE READ`` as
     `snapshot isolation <http://en.wikipedia.org/wiki/Snapshot_isolation>`_,
     which provides the consistency guarantees Odoo requires without
     the performance overhead of true ``SERIALIZABLE`` (which adds
     predicate locking and forced rollbacks for serialization anomalies).
     Odoo handles high-contention paths (stock reservations, sequence
     generation) with explicit row-level locking, so the additional
     heuristics of ``SERIALIZABLE`` mode are unnecessary.

     ``REPEATABLE READ`` is therefore the default isolation level for
     all Odoo cursors (requires PostgreSQL 18+).

     .. attribute:: cache

         Cache dictionary with a "request" (-ish) lifecycle, only lives as
         long as the cursor itself does and proactively cleared when the
         cursor is closed.

         This cache should *only* be used to store repeatable reads as it
         ignores rollbacks and savepoints, it should not be used to store
         *any* data which may be modified during the life of the cursor.

    """

    sql_from_log: dict[str, tuple[int, float]]
    sql_into_log: dict[str, tuple[int, float]]
    sql_log_count: int

    # Class-level default: an instance whose __init__ failed before setting
    # the flag must read as closed.  Also breaks the __getattr__ recursion
    # (`self._closed` lookup re-entering __getattr__) on such instances.
    _closed: bool = True

    def __init__(
        self,
        pool: ConnectionPool,
        dbname: str,
        dsn: dict,
        key: frozenset | None = None,
    ):
        super().__init__()
        self.sql_from_log = {}
        self.sql_into_log = {}

        # default log level determined at cursor creation, could be
        # overridden later for debugging purposes
        self.sql_log_count = 0

        # avoid the call of close() (by __del__) if an exception
        # is raised by any of the following initializations
        self._closed: bool = True

        self.__pool: ConnectionPool = pool
        self.dbname = dbname

        # Cache thread reference — a cursor is always used on its creating
        # thread (hard invariant; violating it corrupts the PG transaction).
        # This avoids calling threading.current_thread() on every execute().
        self._thread = threading.current_thread()

        self._cnx: psycopg.Connection = pool.borrow(dsn, key=key)
        try:
            self._obj: psycopg.Cursor = self._cnx.cursor()
            if _logger.isEnabledFor(logging.DEBUG):
                self.__caller = frame_codeinfo(currentframe(), 2)
            else:
                self.__caller = False
            # See the docstring of this class.
            self._cnx.isolation_level = IsolationLevel.REPEATABLE_READ
            self._cnx.read_only = pool.readonly
            # Cache the mode on the cursor itself — after _close() returns
            # _cnx to the pool, another cursor may own the same connection
            # and flip read_only.  Reading it off _cnx post-close returns
            # stale or foreign state.
            self._readonly = bool(pool.readonly)

            # FAKETIME test mode: pin search_path so it survives a later
            # rollback.  Kept inside this try — and BEFORE the cursor is marked
            # open — so a failure here is unwound by the except below (close
            # _obj + give_back the connection) rather than leaking to __del__,
            # which would emit a spurious "Cursor not closed explicitly"
            # warning and defer the connection's return to GC.
            if (
                os.getenv("ODOO_FAKETIME_TEST_MODE")
                and self.dbname in tools.config["db_name"]
            ):
                self.execute("SET search_path = public, pg_catalog;")
                self.commit()  # persist search_path across later rollbacks

            self._closed = False  # only after all setup succeeds
        except Exception:
            # If _obj was created before the setter failed, close it before
            # returning the connection — psycopg_pool's reset() only rolls
            # back the transaction, it does not close open cursors.
            #
            # Read _obj straight from __dict__, NOT via getattr(): when
            # ``self._cnx.cursor()`` itself raises, _obj was never assigned, and
            # ``getattr(self, "_obj", None)`` would route through the overridden
            # __getattr__ — which sees ``_closed`` still True and raises
            # ``InterfaceError("Cursor already closed")``.  That replacement
            # exception would propagate out of this handler, masking the real
            # error AND skipping the give_back() below — leaking the connection
            # and its _pool_sem permit for the life of the process.
            obj = self.__dict__.get("_obj")
            if obj is not None:
                with suppress(Exception):
                    obj.close()
            pool.give_back(self._cnx)
            raise

    def fetchscalar(self) -> Any:
        row = self._obj.fetchone()
        return row[0] if row else None

    def dictfetchone(self) -> dict[str, Any] | None:
        row = self._obj.fetchone()
        if row is None:
            return None
        desc = self._obj.description
        # Explicit check survives ``python -O`` where ``assert`` is stripped.
        if not desc:
            raise RuntimeError(
                "dictfetchone: cursor has no result description "
                "(query did not produce a result set)"
            )
        # strict=True: psycopg guarantees len(row) == len(description); a
        # mismatch is a driver-level surprise that should raise, not silently
        # drop trailing columns.
        return {col.name: val for col, val in zip(desc, row, strict=True)}

    def _col_names(self) -> tuple[str, ...]:
        """Extract column names from the last query's description as a tuple."""
        return tuple(col.name for col in self._obj.description)

    def _rows_to_dict_list(
        self, rows: list[tuple[Any, ...]]
    ) -> list[dict[str, Any]]:
        """Zip *rows* against the last query's column names into dicts.

        Single source for the rows→dicts conversion shared by
        :meth:`dictfetchmany` and :meth:`dictfetchall`: the Rust fast path
        (``_rows_to_dicts``) and its pure-Python fallback live here only, so a
        future change to either touches one place.  Callers must short-circuit
        empty ``rows`` themselves — an empty fetch may carry no description to
        read column names from.
        """
        if _rows_to_dicts is not None:
            return _rows_to_dicts(self._col_names(), rows)
        cols = self._col_names()
        return [dict(zip(cols, row, strict=True)) for row in rows]

    def dictfetchmany(self, size: int) -> list[dict[str, Any]]:
        # Match BaseCursor.dictfetchmany's ``while size > 0`` contract: a
        # negative size yields no rows.  Without this guard psycopg's
        # fetchmany(-1) raises InterfaceError("rows must be included between
        # 0 and N"), so the base class and its production override disagreed
        # on the exact same invalid input (the base returned []).
        if size <= 0:
            return []
        rows = self._obj.fetchmany(size)
        if not rows:
            return []
        return self._rows_to_dict_list(rows)

    def dictfetchall(self) -> list[dict[str, Any]]:
        rows = self._obj.fetchall()
        if not rows:
            return []
        return self._rows_to_dict_list(rows)

    # -- Explicit forwarding for commonly-used psycopg Cursor methods -------
    # These were previously resolved via __getattr__ on every call.
    # Explicit forwarding avoids attribute-lookup overhead on the hot path
    # and makes the public interface discoverable for IDEs/type checkers.

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._obj.fetchone()

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._obj.fetchall()

    def fetchmany(self, size: int = 0) -> list[tuple[Any, ...]]:
        return self._obj.fetchmany(size)

    @property
    def description(self) -> list[Any] | None:
        return self._obj.description

    @property
    def rowcount(self) -> int:
        return self._obj.rowcount

    def nextset(self) -> bool | None:
        """Move to the next result set (e.g. ``executemany(returning=True)``)."""
        return self._obj.nextset()

    def copy(
        self,
        statement: str | bytes | _sql.Composable,
        params: tuple | list | dict | None = None,
        *,
        writer: Any = None,
    ) -> Any:  # psycopg.Copy — not imported to keep the module surface small
        """Raw passthrough to psycopg's ``cursor.copy()`` COPY context manager.

        Low-level escape hatch: unlike :meth:`copy_from`, this records **no**
        metrics (``sql_counter`` / ``query_count`` / profiler hooks) and does
        **no** error demotion (``_log_sql_error``) — the actual row writes happen
        in the caller's ``with`` block, outside any timing this cursor could wrap.
        Prefer :meth:`copy_from` for bulk inserts (binary mode, pre-generated
        ids, recoverable-error handling, metrics); reach for this only when you
        need direct control over the psycopg ``Copy`` object.
        """
        return self._obj.copy(statement, params, writer=writer)

    def __del__(self) -> None:
        if not self._closed and not self._cnx.closed:
            # Oops. 'self' has not been closed explicitly.
            # The cursor will be deleted by the garbage collector,
            # but the database connection is not put back into the connection
            # pool, preventing some operation on the database like dropping it.
            # This can also lead to a server overload.
            msg = "Cursor not closed explicitly\n"
            if self.__caller:
                msg += f"Cursor was created at {self.__caller[0]}:{self.__caller[1]}"
            else:
                msg += "Please enable sql debugging to trace the caller."
            _logger.warning(msg)
            self._close()

    def execute(
        self,
        query: str | SQL,
        params: tuple | list | dict | None = None,
        log_exceptions: bool = True,
    ) -> None:
        # NB: no `self._thread is threading.current_thread()` assertion here.
        # The actual invariant is "no CONCURRENT execute on the same
        # connection", not "only the creating thread may execute".  Odoo's
        # TestCursor (odoo.tests.test_cursor.TestCursor) deliberately shares
        # the underlying real cursor across the main test thread and HTTP
        # worker threads, serializing access through an RLock so the shared
        # transaction is visible to the HTTP handlers.  A creating-thread
        # check fires false positives on that path.  See ``self._thread``
        # (set in ``__init__``) — it is retained purely for the query-count
        # / query-time metrics to pin stats to the originating thread.

        if isinstance(query, SQL):
            # Explicit check survives ``python -O`` where ``assert`` is
            # stripped — silently dropping caller params would execute a
            # different query than intended.
            if params is not None:
                raise ValueError(
                    "Unexpected parameters combined with a SQL query object"
                )
            query, params = query.code, query.params
        elif params:
            if not isinstance(params, (tuple, list, dict)):
                raise ValueError(  # noqa: TRY004 — legacy contract, exercised by tests
                    f"SQL query parameters should be a tuple, list or dict; got {params!r}"
                )

        # Detect DDL once up-front (see _ddl_keyword for the fast-path gate and
        # the deep-indentation fallback).  The result drives two decisions:
        # before execute, params must be inlined client-side for *every* DDL
        # keyword (DDL structural positions reject server-side $N parameters);
        # after, only *schema-changing* DDL (CREATE/ALTER/DROP/DO) invalidates
        # the prepared-statement and schema caches — COMMENT/GRANT/REVOKE are
        # DDL for param-inlining but never change a relation's shape.
        qs = query if isinstance(query, str) else str(query)
        ddl_kw = _ddl_keyword(qs)  # uppercase keyword, or None when not DDL
        is_ddl = ddl_kw is not None

        if params and is_ddl:
            # DDL rejects server-side $N parameters — inline them client-side
            # as quoted literals (see _inline_ddl_params for the why/how).
            query = _inline_ddl_params(qs, params, self._cnx)
            params = None

        # Resolve the DEBUG gate once (used in the finally below and again for
        # the advanced stats) — computed before ``start`` so the isEnabledFor
        # call never lands inside the measured query window.
        debug = _logger.isEnabledFor(logging.DEBUG)
        # start: wall-clock, forwarded to query hooks so SQL entries align with
        # the profiler's wall-clock frame timeline.  Only the profiler installs
        # query_hooks, so skip the clock read entirely when none are present —
        # the dominant case on this hot path (mirrors the metrics_query gating in
        # copy_from).  t0: monotonic, ALWAYS needed for the duration —
        # ``real_time`` is ``time.time`` (wall-clock), so an NTP step-back
        # mid-query would make ``delay`` negative and corrupt query_time /
        # sql_*_log accumulators.
        start = real_time() if getattr(self._thread, "query_hooks", None) else 0.0
        t0 = monotonic()
        try:
            self._obj.execute(query, params)
        except Exception as e:
            if log_exceptions:
                _log_sql_error(e, query)
            # This ``raise`` exits before the ``_record_metrics`` /
            # ``_record_sql_log`` calls below, so a FAILED statement is
            # deliberately not counted in ``sql_counter`` /
            # ``thread.query_count`` / ``thread.query_time`` — those reflect
            # successfully-executed statements only.  This keeps query-count
            # assertions deterministic under the request/ORM retry loops: a
            # retried serialization failure / deadlock would otherwise inflate
            # the counters by a non-deterministic number of failed attempts.
            raise
        finally:
            delay = monotonic() - t0
            if debug:
                _logger.debug(
                    "[%.3f ms] query: %s",
                    1000 * delay,
                    self._format(query, params),
                )

        if ddl_kw in _SCHEMA_CHANGING_DDL:
            # Only schema-changing DDL reaches here (CREATE/ALTER/DROP/DO);
            # COMMENT/GRANT/REVOKE were inlined above but skip the invalidation,
            # since they never change a relation's shape.
            self._invalidate_caches_after_ddl()

        self._record_metrics(delay, query=query, params=params, start=start)

        # advanced stats (see _record_sql_log; copy_from shares the same path).
        # Categorize on ``qs`` — the query's string form already built for DDL
        # detection — rather than re-stringifying ``query`` (which may now be the
        # param-inlined DDL text): same FROM/INTO table, one fewer str() per query.
        if debug:
            query_type, table = categorize_query(qs)
            self._record_sql_log(query_type, table, delay)

    def _invalidate_caches_after_ddl(self) -> None:
        """Drop the caches a schema-changing DDL on this connection invalidates.

        Two independent caches go stale on CREATE/ALTER/DROP/DO, and neither
        self-heals on the worker that ran the DDL:

        1. **psycopg's auto-prepared-statement cache** on this connection.
           psycopg3's PrepareManager natively handles DROP/ROLLBACK, but
           CREATE/ALTER also change schema — making cached plans for ``SELECT *``
           queries stale ("cached plan must not change result type").  Private
           API: psycopg 3.x has no public method to invalidate it.
           ``_prepared.clear()`` queues a ``DEALLOCATE ALL`` on the next
           execute().  If a future psycopg removes the attribute, disable
           auto-prepare on this connection instead (covers the rest of its
           max_lifetime window).
        2. **The process-global** ``schema_cache`` that ``copy_from`` populates:
           ``ALTER COLUMN ... TYPE`` changes a cached column type, ``DROP``
           removes a cached table/sequence.  These entries are cleared
           cross-worker via registry signalling but never for the worker that
           ran the DDL itself, so a binary ``copy_from`` issued between this DDL
           and the next drain_*/close_db would feed psycopg's ``set_types()``
           stale types and corrupt the COPY (reproduced: "'str' object cannot be
           interpreted as an integer" after an int->text ALTER).  Dropping this
           database's entries forces the next ``copy_from`` to re-look them up.

        Cheap: DDL is rare outside installs/upgrades, and the schema_cache is
        only ever populated by binary / returning_ids ``copy_from``.
        """
        try:
            self._cnx._prepared.clear()
        except AttributeError:
            self._cnx.prepare_threshold = None
        schema_cache.clear(self.dbname)

    def executemany(
        self,
        query: str | SQL,
        params_seq: Iterable[tuple | list | dict],
        returning: bool = False,
        log_exceptions: bool = True,
    ) -> None:
        """Execute a query with multiple parameter sets using pipeline mode.

        psycopg3's executemany automatically batches all statements in a
        single network round-trip on PostgreSQL 14+, avoiding the overhead
        of individual execute() calls.

        :param query: SQL query with ``%s`` placeholders
        :param params_seq: Sequence of parameter tuples/lists
        :param returning: If True, collect RETURNING results per statement.
            Use ``fetchall()`` + ``nextset()`` loop to read all result sets.
        :param log_exceptions: If False, suppress logging of failures (the
            caller logs its own message).  Symmetric with :meth:`execute` —
            without it a caller could quiet single-statement failures but not
            their batched equivalent.
        """
        if isinstance(query, SQL):
            # executemany's params come from params_seq, not the SQL object.
            # Silently dropping embedded params hides caller bugs.
            if query.params:
                raise ValueError(
                    "executemany does not support SQL objects with embedded "
                    "params; pass the per-row params via params_seq instead."
                )
            query = query.code

        # Materialize once if the sequence is not sized.  A generator is always
        # truthy (so ``if not params_seq`` would NOT short-circuit an empty one,
        # unlike an empty list) and has no ``len()`` (so the metrics count below
        # would silently record 1 for an N-row batch).  psycopg's executemany
        # consumes the iterable once internally anyway, so this adds no extra
        # pass for the common list/tuple caller.
        if not hasattr(params_seq, "__len__"):
            params_seq = list(params_seq)
        if not params_seq:
            return

        # ``start`` is consumed only by query_hooks (profiler); skip the
        # wall-clock read when none are installed.  t0 (monotonic) is always
        # needed for the duration.  See execute() for the NTP rationale.
        start = real_time() if getattr(self._thread, "query_hooks", None) else 0.0
        t0 = monotonic()
        try:
            self._obj.executemany(query, params_seq, returning=returning)
        except Exception as e:
            if log_exceptions:
                _log_sql_error(e, query)
            raise
        finally:
            delay = monotonic() - t0
            if _logger.isEnabledFor(logging.DEBUG):
                _logger.debug(
                    "[%.3f ms] executemany (%d rows): %s",
                    1000 * delay,
                    len(params_seq),  # always sized: materialized above
                    query,
                )

        self._record_metrics(delay, len(params_seq), query=query, start=start)

    @contextmanager
    def pipeline(self) -> Generator[None]:
        """Enter pipeline mode for batching queries in a single round-trip.

        All execute() calls within the context are queued and sent together
        when the context exits, reducing network overhead for batch operations.

        Usage::

            with cr.pipeline():
                cr.execute("INSERT INTO t1 ...")
                cr.execute("INSERT INTO t2 ...")
                # Both sent in one round-trip

        .. note::
            Per-query timing is unreliable inside a pipeline.  ``execute()``
            returns as soon as a statement is *queued* — the server runs the
            whole batch only when the context exits — so each query's recorded
            ``delay`` (and the profiler ``query_hooks`` / ``sql_*_log`` entries
            built from it) reflects enqueue time, ~0 ms, not execution time.
            The batch's real cost lands at context exit, attributed to no single
            query.  Counts (``sql_log_count``/``sql_counter``) stay accurate;
            only the durations are skewed.
        """
        with self._cnx.pipeline():
            yield

    def close(self) -> None:
        # Intentionally test self._closed, NOT self.closed.  The property
        # also returns True when _cnx.closed flips (network failure, peer
        # drop).  If we short-circuit on it, _close() never runs and the
        # semaphore slot plus self._obj leak for the life of the process.
        if not self._closed:
            self._close()

    def _close(self) -> None:
        # No ``if not self._obj`` guard here: a psycopg3 cursor has no
        # __bool__/__len__ (it is always truthy), and _close() is only ever
        # reached via close()/__del__, both gated on ``_closed`` — so _obj is
        # always a live cursor on entry.  The old guard was dead (a psycopg2
        # leftover where the attribute could be None).
        self.cache.clear()

        # advanced stats only at logging.DEBUG level
        self.print_log()

        self._obj.close()

        # Mark cursor as closed BEFORE deleting _obj. This prevents
        # __getattr__ from entering infinite recursion if a rollback
        # hook accidentally accesses a delegated attribute (since _obj
        # no longer exists but _closed would still be False).
        self._closed = True

        # This force the cursor to be freed, and thus, available again. It is
        # important because otherwise we can overload the server very easily
        # because of a cursor shortage (because cursors are not garbage
        # collected as fast as they should). The problem is probably due in
        # part because browse records keep a reference to the cursor.
        del self._obj

        # Clean the underlying connection, then return it to the pool.
        # give_back() MUST run even if rollback() fails (e.g. broken
        # connection, failing hooks) — otherwise the connection and its
        # global semaphore slot leak permanently.
        chosen_template = tools.config["db_template"]
        keep_in_pool = self.dbname not in (
            "template0",
            "template1",
            "postgres",
            chosen_template,
        )
        try:
            self.rollback()
        except Exception:
            _logger.debug("Failed to rollback on cursor close", exc_info=True)
            keep_in_pool = False
        finally:
            self.__pool.give_back(self._cnx, keep_in_pool=keep_in_pool)

    def commit(self) -> None:
        """Perform an SQL `COMMIT`"""
        # Explicit check (not assert): must survive ``python -O`` — a commit
        # inside a savepoint corrupts the savepoint's rollback state.  Guarded on
        # the cursor-level depth (see ``_savepoint_depth``) so it fires for EVERY
        # open savepoint, including bare (transaction-less) cursors and
        # ``savepoint(flush=False)`` — cases an ORM-transaction-scoped counter
        # would miss, letting the COMMIT destroy the savepoint and surface later
        # as a confusing ``InvalidSavepointSpecification`` at savepoint close.
        if self._savepoint_depth:
            raise RuntimeError(
                "Cannot commit inside a savepoint! "
                "This would corrupt the savepoint's rollback state."
            )
        self.flush()
        self._cnx.commit()
        self.clear()
        self._now = None
        self.prerollback.clear()
        self.postrollback.clear()
        self.postcommit.run()

    def rollback(self) -> None:
        """Perform an SQL `ROLLBACK`.

        Hook order is intentional: prerollback runs BEFORE the SQL ROLLBACK
        so hooks can still read uncommitted transaction state (e.g. for cache
        invalidation decisions).  After ROLLBACK, that data is gone.
        """
        # Explicit check (not assert): must survive ``python -O``.  Cursor-level
        # depth (see commit() and ``_savepoint_depth``) so the guard also covers
        # bare cursors and ``savepoint(flush=False)``.
        if self._savepoint_depth:
            raise RuntimeError(
                "Cannot rollback inside a savepoint! "
                "Use cr.savepoint() for nested transaction control."
            )
        self.clear()
        self.postcommit.clear()
        self.prerollback.run()
        self._cnx.rollback()
        self._now = None
        self.postrollback.run()

    def __getattr__(self, name: str) -> Any:
        # Short-circuit on closed: any attribute access on a dead cursor
        # raises cleanly, instead of emitting a misleading deprecation
        # warning about the attribute name en route to InterfaceError.
        if self._closed:
            msg = "Cursor already closed"
            raise psycopg.InterfaceError(msg)
        warnings.warn(
            f"Cursor.{name} is not part of the Odoo cursor API. "
            f"Add explicit forwarding in cursor.py or use cr._obj.{name} directly.",
            DeprecationWarning,
            stacklevel=2,
        )
        return getattr(self._obj, name)

    @property
    def closed(self) -> bool:
        return self._closed or bool(self._cnx.closed)

    @property
    def connection(self) -> psycopg.Connection:
        """The underlying psycopg connection.

        Exposed as an explicit property — not generic ``__getattr__`` forwarding —
        because cron workers hold a long-lived reference for ``LISTEN``/``NOTIFY``
        and selector registration. Routing through ``__getattr__`` would emit a
        ``DeprecationWarning`` on every poll, and opaque forwarding makes the
        connection's lifetime relative to the cursor harder to reason about.
        """
        return self._cnx

    @property
    def readonly(self) -> bool:
        return self._readonly


if TYPE_CHECKING:
    # Single-source-of-truth guard for the bulk-access coupling: assert that
    # Cursor actually provides every member _BulkAccessMixin declares it needs
    # (see _CursorInternals in bulk.py).  This is a pure static check — the
    # function is never defined at runtime — so any drift between Cursor and
    # that Protocol surfaces as a type error here instead of a latent
    # AttributeError inside copy_from / execute_values.
    from .bulk import _CursorInternals

    def _assert_cursor_satisfies_bulk_host(_c: Cursor) -> _CursorInternals:
        return _c

    # Same guard for the metrics-mixin coupling: Cursor must provide every member
    # _MetricsMixin's methods read off ``self`` (see _MetricsHost in metrics.py).
    from .metrics import _MetricsHost

    def _assert_cursor_satisfies_metrics_host(_c: Cursor) -> _MetricsHost:
        return _c
