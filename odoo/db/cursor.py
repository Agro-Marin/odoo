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

# Rust-accelerated rows→dicts conversion (~2.5x faster than pure Python).
from odoo_rust import rows_to_dicts as _rows_to_dicts
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
from .pool import ConnectionPool
from .savepoint import Savepoint, _FlushingSavepoint
from .schema_cache import schema_cache
from .utils import categorize_query, is_maintenance_db

if TYPE_CHECKING:
    from odoo.orm.runtime import Transaction

    # when type checking, the BaseCursor exposes methods of the psycopg cursor
    _CursorProtocol = psycopg.Cursor
else:
    _CursorProtocol = object

_logger = logging.getLogger(__name__)


def _clear_schema_caches(dbname: str | None = None) -> None:
    """Drop cached schema lookups (column types, id sequences).

    Delegating wrapper kept as :mod:`odoo.db`'s cache-invalidation hook (called
    from ``close_db`` / ``drain_*``); the state and clear logic live in
    :class:`~odoo.db.schema_cache.SchemaCache`.

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
    # :class:`_FlushingSavepoint`; the ORM overrides it on import with its
    # cache/env-restoring subclass, keeping the db→ORM dependency one-directional.
    _flushing_savepoint_cls: type[Savepoint] = _FlushingSavepoint

    transaction: Transaction | None
    cache: dict[Any, Any]
    dbname: str
    # Number of SAVEPOINTs currently open on THIS cursor.  Maintained by every
    # ``Savepoint`` and read by ``Cursor.commit``/``rollback`` to forbid
    # committing/rolling back the whole transaction while a savepoint is live.
    # Lives on the cursor (not the ORM ``transaction``) so it also guards bare
    # ``db_connect`` cursors and ``savepoint(flush=False)``.
    _savepoint_depth: int

    def __init__(self) -> None:
        self.precommit = Callbacks()
        self.postcommit = Callbacks()
        self.prerollback = Callbacks()
        self.postrollback = Callbacks()
        self._now: datetime | None = None
        self._savepoint_depth = 0
        self.cache = {}
        # Attached lazily by ``Environment.__new__`` on first Environment
        # construction (not by ``registry.cursor()``); done there, not here, to
        # avoid a cyclic module dependency.
        self.transaction = None

    def flush(self) -> None:
        """Flush the current transaction, and run precommit hooks.

        Convergence contract: a precommit hook signals follow-up work by
        dirtying the ORM (which the next pass re-queues), NOT by re-adding itself
        to ``self.precommit``.  ``_MAX_FLUSH_PASSES`` bounds this cross-pass
        ping-pong; a hook that unconditionally re-adds itself instead loops
        forever inside ``Callbacks.run()``.
        """
        # Repeat flush + drain until a pass produces no new work.
        for _ in range(self._MAX_FLUSH_PASSES):
            if self.transaction is not None:
                self.transaction.flush()
            if not self.precommit:
                return
            self.precommit.run()
        # Final flush after the last drain: the convergence check runs *before*
        # each ``run()``, so without this the last run's effect is never
        # re-examined and a chain settling on the final pass would raise spuriously.
        if self.transaction is not None:
            self.transaction.flush()
        if self.precommit:
            # Raise, don't warn: commit() would otherwise COMMIT and clear()
            # the still-pending hooks, silently dropping their work.
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
        """Reset the current transaction (this invalidates more than clear()).
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
        """Open a new savepoint, returned as a context manager.

        With ``flush`` (the default), will automatically run (or clear) the
        relevant hooks.  The flushing variant is resolved via
        ``_flushing_savepoint_cls`` so the ORM layer can inject its
        cache/env-restoring subclass without the db layer importing it.
        """
        if flush:
            cls = self._flushing_savepoint_cls
            # Fail loudly instead of silently corrupting the cache: a cursor with
            # an ORM transaction MUST use a savepoint that restores ORM state on
            # rollback.  If it doesn't, the ORM injection seam (set as an import
            # side effect of ``odoo.orm.runtime``) was not wired — a broken import
            # order — and ``ROLLBACK TO SAVEPOINT`` would leave a stale cache.
            if self.transaction is not None and not cls._restores_orm_state:
                raise RuntimeError(
                    f"cursor has an ORM transaction but {cls.__name__} does not "
                    "restore ORM state on rollback; the odoo.orm.runtime savepoint "
                    "seam was not installed (import-order bug)."
                )
            return cls(self)
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
            # Skip the commit when the block already closed the cursor: there is
            # nothing to commit and the connection is back in the pool (commit()
            # would now raise on the closed cursor).
            if exc_type is None and not self._closed:
                self.commit()
        finally:
            self.close()

    def fetchscalar(self) -> Any:
        """Fetch a single scalar value from a single-column query.

        Returns ``None`` if no rows are available.  Eliminates the
        common ``cr.fetchone()[0]`` pattern which raises on empty results.
        """
        # Implemented over fetchone() rather than left abstract: a
        # ``NotImplementedError`` body would be found by MRO and shadow the
        # __getattr__ delegation TestCursor relies on (fetchone() is deliberately
        # not declared on the base, so TestCursor forwards it to the real
        # cursor).  Cursor overrides this to save one attribute hop.
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
            # A SELECT always yields exactly one row, so fetchone() is never None.
            self._now = self.fetchone()[0]
        return self._now


class Cursor(_BulkAccessMixin, _MetricsMixin, BaseCursor):
    """Represents an open transaction to the PostgreSQL DB backend,
    acting as a lightweight wrapper around psycopg's
    ``Cursor`` objects (native server-side binding).

     ``Cursor`` is the object behind the ``cr`` variable used all
     over the Odoo code.

     .. rubric:: Transaction Isolation

     All Odoo cursors default to ``REPEATABLE READ``, which PostgreSQL
     implements as
     `snapshot isolation <http://en.wikipedia.org/wiki/Snapshot_isolation>`_.
     This gives the consistency Odoo needs without ``SERIALIZABLE``'s overhead
     (predicate locking, serialization-anomaly rollbacks); high-contention paths
     (stock reservations, sequence generation) use explicit row-level locking
     instead.

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

    # Class-level default so an instance whose __init__ failed reads as closed
    # (and the ``self._closed`` lookup in __getattr__ doesn't recurse).
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

        self.sql_log_count = 0

        # __del__ calls close() only when _closed is False; keep it True until
        # init fully succeeds so a failure below doesn't trigger close().
        self._closed: bool = True

        self.__pool: ConnectionPool = pool
        self.dbname = dbname

        # Cache the creating thread (avoids threading.current_thread() per
        # execute()); used only to pin query-count/time metrics to that thread.
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
            # Cache the mode on the cursor: after _close() returns _cnx to the
            # pool another cursor may own it and flip read_only, so reading it
            # off _cnx post-close would return stale/foreign state.
            self._readonly = bool(pool.readonly)

            # FAKETIME test mode: pin search_path so it survives a later
            # rollback.  Inside this try (and before _closed=False) so a failure
            # is unwound by the except below rather than leaking to __del__.
            if (
                os.getenv("ODOO_FAKETIME_TEST_MODE")
                and self.dbname in tools.config["db_name"]
            ):
                self.execute("SET search_path = public, pg_catalog;")
                # Commit on the raw connection: the public ``commit()`` guards
                # on ``self._closed`` (still True here, so it would raise
                # "Cursor already closed"), and no ORM flush/savepoint state
                # exists yet during __init__. Persists search_path across later
                # rollbacks.
                self._cnx.commit()

            self._closed = False  # only after all setup succeeds
        except Exception:
            # Close _obj if it was created (psycopg_pool's reset() rolls back
            # but does not close open cursors), then return the connection.
            # Read _obj from __dict__, not getattr(): if ``_cnx.cursor()`` itself
            # raised, _obj is unset and getattr would route through __getattr__
            # (``_closed`` still True → InterfaceError), masking the real error
            # and skipping give_back() — leaking the connection and its permit.
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
        # A returned row guarantees a result set — a result-less statement makes
        # fetchone() raise, not return a row — hence a non-empty description.
        # strict=True: psycopg guarantees len(row) == len(description), so a
        # mismatch is a driver bug that should raise, not drop columns.
        return {
            col.name: val for col, val in zip(self._obj.description, row, strict=True)
        }

    def _col_names(self) -> tuple[str, ...]:
        """Extract column names from the last query's description as a tuple."""
        return tuple(col.name for col in self._obj.description)

    def _rows_to_dict_list(self, rows: list[tuple[Any, ...]]) -> list[dict[str, Any]]:
        """Zip *rows* against the last query's column names into dicts.

        Shared by :meth:`dictfetchmany`/:meth:`dictfetchall`.  Callers must
        short-circuit empty ``rows`` (an empty fetch may carry no description).
        """
        return _rows_to_dicts(self._col_names(), rows)

    def dictfetchmany(self, size: int) -> list[dict[str, Any]]:
        # Match BaseCursor.dictfetchmany: size <= 0 yields no rows.  Without
        # this, psycopg's fetchmany(-1) raises InterfaceError instead.
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
    # Avoids __getattr__ lookup overhead on the hot path and makes the public
    # interface discoverable for IDEs/type checkers.

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

        Low-level escape hatch: unlike :meth:`copy_from` it records no metrics
        and does no error demotion (the row writes happen in the caller's
        ``with`` block).  Prefer :meth:`copy_from` for bulk inserts; reach for
        this only when you need the raw psycopg ``Copy`` object.
        """
        return self._obj.copy(statement, params, writer=writer)

    def __del__(self) -> None:
        if not self._closed and not self._cnx.closed:
            # Not closed explicitly: GC will reclaim the cursor, but the
            # connection is not returned to the pool — risking pool exhaustion
            # and blocking operations like dropping the database.
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
        # No creating-thread assertion here: the real invariant is "no
        # CONCURRENT execute on the same connection", not "same thread".
        # TestCursor deliberately shares one real cursor across the test and
        # HTTP worker threads (serialized by an RLock), which a thread check
        # would flag.  ``self._thread`` is kept only to pin metrics.

        if isinstance(query, SQL):
            # Explicit check (survives ``python -O``): silently dropping params
            # would execute a different query than intended.
            if params is not None:
                raise ValueError(
                    "Unexpected parameters combined with a SQL query object"
                )
            query, params = query.code, query.params
        elif params:
            if not isinstance(params, (tuple, list, dict)):
                raise ValueError(
                    f"SQL query parameters should be a tuple, list or dict; got {params!r}"
                )

        # Detect DDL once.  It drives two decisions: every DDL keyword needs
        # client-side param inlining ($N is rejected in DDL positions), but only
        # schema-changing DDL (CREATE/ALTER/DROP/DO) invalidates the caches.
        # ``query`` is always a str here: an SQL object was unwrapped to its str
        # ``.code`` above and the public contract is ``str | SQL``, so there is
        # nothing to coerce — a ``str(query)`` fallback would only mask a
        # contract violation (and mangle a stray bytes query into its repr).
        qs = query
        ddl_kw = _ddl_keyword(qs)  # uppercase keyword, or None when not DDL
        is_ddl = ddl_kw is not None

        if params and is_ddl:
            # Inline params as client-side quoted literals (see _inline_ddl_params).
            query = _inline_ddl_params(qs, params, self._cnx)
            params = None

        # Resolve the DEBUG gate once, before ``start``, so isEnabledFor stays
        # out of the measured window.
        debug = _logger.isEnabledFor(logging.DEBUG)
        # Read the thread's query_hooks once: it gates the wall-clock ``start``
        # (skipped when no profiler is installed) and is handed to
        # ``_record_metrics`` below, so this hot path touches the thread attribute
        # once instead of twice.  t0 (monotonic) always times the query —
        # wall-clock could step back under NTP and make ``delay`` negative.
        hooks = getattr(self._thread, "query_hooks", None)
        start = real_time() if hooks else 0.0
        t0 = monotonic()
        try:
            self._obj.execute(query, params)
        except Exception as e:
            if log_exceptions:
                _log_sql_error(e, query)
            # Failed statements are deliberately not counted (the raise exits
            # before _record_metrics): counters reflect successful queries only,
            # keeping query-count assertions deterministic across retry loops.
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
            # COMMENT/GRANT/REVOKE are DDL but don't change shape, so they skip this.
            self._invalidate_caches_after_ddl()

        self._record_metrics(
            delay, query=query, params=params, start=start, hooks=hooks
        )

        # Advanced stats (DEBUG only).  Categorize on ``qs`` (already built for
        # DDL detection) — same table, one fewer str() than re-stringifying query.
        if debug:
            query_type, table = categorize_query(qs)
            self._record_sql_log(query_type, table, delay)

    def _invalidate_caches_after_ddl(self) -> None:
        """Drop the caches a schema-changing DDL invalidates on this connection.

        Two caches go stale on CREATE/ALTER/DROP/DO and neither self-heals on
        the worker that ran the DDL:

        1. psycopg's auto-prepared-statement cache on this connection: CREATE/
           ALTER make cached ``SELECT *`` plans stale ("cached plan must not
           change result type").  ``_prepared.clear()`` (private API) queues a
           ``DEALLOCATE ALL``; if a future psycopg drops it, the fallback both
           disables auto-prepare AND issues ``DEALLOCATE ALL`` itself —
           ``prepare_threshold = None`` alone only stops preparing NEW
           statements, leaving the already-cached stale plans in place.
        2. The process-global ``schema_cache`` ``copy_from`` populates: ALTER/
           DROP make cached column types/sequences stale.  Other workers are
           cleared via registry signalling, but not the one that ran the DDL, so
           a later binary ``copy_from`` would feed ``set_types()`` stale types
           and corrupt the COPY.  Drop this db's entries to force a re-lookup.
        """
        try:
            self._cnx._prepared.clear()
        except AttributeError:
            # Private API gone: disabling auto-prepare stops NEW prepares but
            # leaves the existing stale plans, so drop them explicitly too.  Safe
            # here — we only reach this after a *successful* DDL, so the
            # transaction is healthy and DEALLOCATE ALL can run inside it.
            self._cnx.prepare_threshold = None
            self._cnx.execute("DEALLOCATE ALL")
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

        # Materialize an unsized sequence: a generator is always truthy (so the
        # empty check below would miss an empty one) and has no len() (so metrics
        # would record 1 for an N-row batch).  Sized callers pay nothing.
        if not hasattr(params_seq, "__len__"):
            params_seq = list(params_seq)
        if not params_seq:
            return

        # ``start`` is consumed only by query_hooks (profiler); skip the
        # wall-clock read when none are installed.  t0 (monotonic) is always
        # needed for the duration.  See execute() for the NTP rationale and the
        # single-read-of-query_hooks rationale.
        hooks = getattr(self._thread, "query_hooks", None)
        start = real_time() if hooks else 0.0
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

        self._record_metrics(
            delay, len(params_seq), query=query, start=start, hooks=hooks
        )

        # Advanced per-table stats (DEBUG only), mirroring execute() so batched
        # writes aren't invisible in the SQL log.  ``query`` is always a str here
        # (SQL unwrapped above) and executemany is never DDL.
        if _logger.isEnabledFor(logging.DEBUG):
            query_type, table = categorize_query(query)
            self._record_sql_log(query_type, table, delay)

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
            Per-query timing is unreliable here: ``execute()`` returns when a
            statement is *queued*, so each recorded ``delay`` reflects enqueue
            time (~0 ms), and the batch's real cost lands at context exit
            attributed to no single query.  Counts stay accurate; durations skew.
        """
        with self._cnx.pipeline():
            yield

    def close(self) -> None:
        # Test self._closed, NOT self.closed: the property also reports True on
        # a dropped _cnx, so short-circuiting on it would skip _close() and leak
        # the semaphore slot and self._obj.
        if not self._closed:
            self._close()

    def _close(self) -> None:
        # No ``if not self._obj`` guard: _close() is only reached via
        # close()/__del__ (both gated on ``_closed``), so _obj is always live.
        self.cache.clear()

        # advanced stats only at logging.DEBUG level
        self.print_log()

        self._obj.close()

        # Mark closed BEFORE deleting _obj: otherwise a delegated attribute
        # access (e.g. from a rollback hook) would recurse in __getattr__.
        self._closed = True

        # Free the cursor eagerly: cursors aren't GC'd promptly (browse records
        # hold references), and a shortage can overload the server.
        del self._obj

        # Return the connection to the pool.  give_back() MUST run even if
        # rollback() fails, or the connection and its semaphore slot leak.
        # Never keep connections to system/template databases: an idle one
        # blocks CREATE DATABASE (see utils.is_maintenance_db, which the pool
        # also consults to suppress minconn warming for these).
        keep_in_pool = not is_maintenance_db(self.dbname)
        try:
            # Guard-free: _closed is already True here, and the connection is
            # still owned (give_back runs in the finally below).
            self._do_rollback()
        except Exception:
            _logger.debug("Failed to rollback on cursor close", exc_info=True)
            keep_in_pool = False
        finally:
            self.__pool.give_back(self._cnx, keep_in_pool=keep_in_pool)

    def commit(self) -> None:
        """Perform an SQL `COMMIT`"""
        # Closed-guard: after _close() returns the connection to the pool,
        # self._cnx may be checked out by another cursor in another thread; a
        # public commit here would commit that foreign transaction.  Misuse
        # raises rather than corrupts, matching the savepoint-depth check below.
        if self._closed:
            raise psycopg.InterfaceError("Cursor already closed")
        # Explicit check (survives ``python -O``): committing inside a savepoint
        # corrupts its rollback state.  Cursor-level depth (see
        # ``_savepoint_depth``) so it also covers bare cursors and
        # ``savepoint(flush=False)``.
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
        # Closed-guard: see commit(); a public rollback on a returned connection
        # would roll back a foreign transaction.  _close() uses the guard-free
        # _do_rollback() below (it still owns the connection although _closed).
        if self._closed:
            raise psycopg.InterfaceError("Cursor already closed")
        # Explicit check (survives ``python -O``); cursor-level depth, see commit().
        if self._savepoint_depth:
            raise RuntimeError(
                "Cannot rollback inside a savepoint! "
                "Use cr.savepoint() for nested transaction control."
            )
        self._do_rollback()

    def _do_rollback(self) -> None:
        """Roll back the connection and run the rollback hooks, without the
        closed/savepoint guards.  Used by the public :meth:`rollback` after its
        guards, and by :meth:`_close` where the connection is still owned but
        ``_closed`` is already set."""
        self.clear()
        self.postcommit.clear()
        self.prerollback.run()
        self._cnx.rollback()
        self._now = None
        self.postrollback.run()

    def __getattr__(self, name: str) -> Any:
        # Short-circuit on closed so access to a dead cursor raises cleanly
        # instead of emitting a misleading deprecation warning first.
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

        An explicit property (not ``__getattr__`` forwarding) because cron
        workers hold a long-lived reference for ``LISTEN``/``NOTIFY``; forwarding
        would emit a ``DeprecationWarning`` on every poll.
        """
        return self._cnx

    @property
    def readonly(self) -> bool:
        return self._readonly


if TYPE_CHECKING:
    # Static guard: assert Cursor provides every member _BulkAccessMixin needs
    # (see _CursorInternals in bulk.py), so drift is a type error here, not a
    # latent AttributeError inside copy_from / execute_values.
    from .bulk import _CursorInternals

    def _assert_cursor_satisfies_bulk_host(_c: Cursor) -> _CursorInternals:
        return _c

    # Same guard for the metrics-mixin coupling (see _MetricsHost in metrics.py).
    from .metrics import _MetricsHost

    def _assert_cursor_satisfies_metrics_host(_c: Cursor) -> _MetricsHost:
        return _c
