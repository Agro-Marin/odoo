import logging
import os
import threading
from collections.abc import Generator, Iterable
from contextlib import contextmanager, suppress
from datetime import datetime
from inspect import currentframe
from time import monotonic
from typing import TYPE_CHECKING, Any, NoReturn, Self

import psycopg
from odoo_rust import rows_to_dicts as _rows_to_dicts
from psycopg import IsolationLevel
from psycopg import sql as _sql
from psycopg.pq import TransactionStatus as _TxStatus

from odoo import tools
from odoo.libs.func import frame_codeinfo
from odoo.tools import SQL
from odoo.tools.misc import Callbacks, real_time

from .bulk import _BulkAccessMixin
from .ddl import (
    _changes_schema,
    _ddl_keyword,
    _inline_ddl_params,
    _is_rollback_to_savepoint,
)
from .errors import _log_sql_error
from .metrics import _MetricsMixin
from .pool import ConnectionPool
from .savepoint import Savepoint, _FlushingSavepoint
from .schema_cache import TransactionSchemaCache
from .utils import categorize_query

if TYPE_CHECKING:
    from odoo.orm.runtime import Transaction

_logger = logging.getLogger(__name__)

_TX_IDLE = _TxStatus.IDLE


class BaseCursor:
    """Base class for cursors that manage pre/post commit hooks.

    Declares only what every cursor flavour genuinely provides.  This used to
    inherit ``psycopg.Cursor`` under ``TYPE_CHECKING`` and ``object`` at
    runtime, which told the type checker that every subclass — including
    ``odoo.tests.cursor.TestCursor``, which forwards by ``__getattr__`` — had
    psycopg's whole cursor API.  ``cr.stream(...)`` and ``cr.scroll(...)``
    type-checked clean while resolving at runtime through two layers of
    ``__getattr__``, which is precisely how the bulk-write savepoint bypass
    (see :meth:`_before_statement`) stayed invisible to mypy.

    ``close`` and ``fetchone`` are declared under ``TYPE_CHECKING`` only, never
    defined: :class:`Cursor` implements them, while ``TestCursor`` reaches the
    real cursor through ``__getattr__``, which Python consults only when normal
    lookup fails.  Giving them runtime bodies here — even ones that raise —
    shadows that forwarding and breaks every ``fetchone`` on a test cursor.
    """

    BATCH_SIZE = 1000
    _MAX_FLUSH_PASSES = 10

    _flushing_savepoint_cls: type[Savepoint] = _FlushingSavepoint

    transaction: Transaction | None
    cache: dict[Any, Any]
    dbname: str
    _savepoint_depth: int = 0
    _closed: bool = False

    def __init__(self) -> None:
        self.precommit = Callbacks()
        self.postcommit = Callbacks()
        self.prerollback = Callbacks()
        self.postrollback = Callbacks()
        self._now: datetime | None = None
        self._savepoint_depth = 0
        self.cache = {}
        self.transaction = None

    def flush(self) -> None:
        """Flush the current transaction, and run precommit hooks.

        Convergence contract: a precommit hook signals follow-up work by
        dirtying the ORM (which the next pass re-queues), NOT by re-adding itself
        to ``self.precommit``.  ``_MAX_FLUSH_PASSES`` bounds this cross-pass
        ping-pong; a hook that unconditionally re-adds itself instead loops
        forever inside ``Callbacks.run()``.
        """
        for _ in range(self._MAX_FLUSH_PASSES):
            if self.transaction is not None:
                self.transaction.flush()
            if not self.precommit:
                return
            self.precommit.run()
        if self.transaction is not None:
            self.transaction.flush()
        if self.precommit:
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

    def discard_cached_plans(self) -> None:
        """Drop cached statement plans held by the underlying connection."""

    def _before_statement(self) -> None:
        """Hook: a statement is about to reach the server through this cursor.

        Called by every statement-issuing entry point (``execute``,
        ``executemany``, ``execute_values``, ``copy_from``, ``copy``) and a
        no-op in this layer.  Its job is to *mark* that set: it is the machine-
        readable answer to "which methods put a statement on the wire", which is
        what lets a wrapper cursor be checked for covering all of them.

        ``odoo.tests.cursor.TestCursor`` is the wrapper that needs it — it takes
        a rollback savepoint before the first statement of each test.  Only its
        ``execute()`` override did so, and the bulk APIs it does not override
        reach the real cursor through ``__getattr__``, so their writes landed
        outside the savepoint and survived the rollback.  ``TestCursor`` now
        forwards each marked name explicitly, and a test pins the two lists
        against each other; a write API added here without a matching forwarder
        fails that test instead of silently escaping the savepoint.
        """

    def _on_rollback_to_savepoint(self) -> None:
        """Hook: a ``ROLLBACK TO SAVEPOINT`` just undid part of this transaction.

        No-op here — only the real :class:`Cursor` carries transaction-scoped
        catalog facts that a partial rollback can invalidate.  Declared on the
        base (like :meth:`discard_cached_plans`) so :class:`Savepoint` can call
        it without knowing which cursor flavour it holds.
        """

    def execute(
        self,
        query: str | bytes | SQL | _sql.Composable,
        params: tuple | list | dict | None = None,
        log_exceptions: bool = True,
        prepare: bool | None = None,
    ) -> None:
        """Execute a query inside the current transaction.

        ``prepare`` is forwarded to psycopg: ``None`` keeps the automatic
        behaviour, ``False`` opts the statement out of the prepared-statement
        cache (see :meth:`Cursor.execute`).  Detected DDL defaults to ``False``:
        psycopg auto-prepares parameterless statements too, so a repeated
        ``CREATE``/``ALTER`` was being parsed into a prepared statement that
        :meth:`Cursor._invalidate_caches_after_ddl` then deallocated on the very
        next query.
        """
        raise NotImplementedError

    def commit(self) -> None:
        """Commit the current transaction."""
        raise NotImplementedError

    def rollback(self) -> None:
        """Rollback the current transaction."""
        raise NotImplementedError

    if TYPE_CHECKING:

        def close(self) -> None:
            """Release the cursor and whatever connection it holds."""

        def fetchone(self) -> tuple[Any, ...] | None:
            """Return the next row of the current result set, or ``None``."""

    def savepoint(self, flush: bool = True) -> Savepoint:
        """Open a new savepoint, returned as a context manager.

        With ``flush`` (the default), will automatically run (or clear) the
        relevant hooks.  The flushing variant is resolved via
        ``_flushing_savepoint_cls`` so the ORM layer can inject its
        cache/env-restoring subclass without the db layer importing it.
        """
        if flush:
            cls = self._flushing_savepoint_cls
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
            if exc_type is None and not self._closed:
                self.commit()
        finally:
            self.close()

    def fetchscalar(self) -> Any:
        """Fetch a single scalar value from a single-column query.

        Returns ``None`` if no rows are available.  Eliminates the
        common ``cr.fetchone()[0]`` pattern which raises on empty results.
        """
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

         Whether it survives a rollback depends on a layer above: an attached
         :class:`~odoo.orm.runtime.transaction.Transaction` clears it from
         ``Transaction.clear()``, which runs on both ``rollback()`` and
         ``ROLLBACK TO SAVEPOINT``; a bare cursor with no transaction keeps its
         entries across both. Do not rely on either -- store only repeatable
         reads here, and never data that changes during the life of the cursor.
         A writer that must cache mutable state (``res.currency``'s rate
         history, say) owns invalidating its own key on every mutation.

    """

    sql_from_log: dict[str, tuple[int, float]]
    sql_into_log: dict[str, tuple[int, float]]
    sql_log_count: int

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

        self._closed: bool = True

        self.__pool: ConnectionPool = pool
        self.dbname = dbname

        self._schema_cache = TransactionSchemaCache()

        self._thread = threading.current_thread()

        self._cnx: psycopg.Connection = pool.borrow(dsn, key=key)
        try:
            self._obj: psycopg.Cursor = self._cnx.cursor()
            if _logger.isEnabledFor(logging.DEBUG):
                self.__caller = frame_codeinfo(currentframe(), 2)
            else:
                self.__caller = False
            self._cnx.isolation_level = IsolationLevel.REPEATABLE_READ
            self._cnx.read_only = pool.readonly
            self._readonly = bool(pool.readonly)

            if (
                os.getenv("ODOO_FAKETIME_TEST_MODE")
                and self.dbname in tools.config["db_name"]
            ):
                self.execute("SET search_path = public, pg_catalog;")
                self._cnx.commit()

            self._closed = False
        except Exception:
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
    ) -> Any:
        """Raw passthrough to psycopg's ``cursor.copy()`` COPY context manager.

        Low-level escape hatch: unlike :meth:`copy_from` it records no metrics
        and does no error demotion (the row writes happen in the caller's
        ``with`` block).  Prefer :meth:`copy_from` for bulk inserts; reach for
        this only when you need the raw psycopg ``Copy`` object.
        """
        self._before_statement()
        return self._obj.copy(statement, params, writer=writer)

    def _refuse_copy(self) -> NoReturn:
        raise TypeError(
            f"{type(self).__name__} cannot be copied: it owns a borrowed pooled "
            f"connection and an open transaction.  A shallow copy shares "
            f"``_obj``/``_cnx``, so the copy's ``__del__`` would roll back and "
            f"return the connection to the pool while the original is still "
            f"using it (and log a spurious 'Cursor not closed explicitly').  "
            f"Pass the cursor around, or open a second one via "
            f"``registry.cursor()``."
        )

    def __copy__(self) -> NoReturn:
        self._refuse_copy()

    def __deepcopy__(self, memo: dict) -> NoReturn:
        self._refuse_copy()

    def __del__(self) -> None:
        if not self._closed and not self._cnx.closed:
            msg = "Cursor not closed explicitly\n"
            if self.__caller:
                msg += f"Cursor was created at {self.__caller[0]}:{self.__caller[1]}"
            else:
                msg += "Please enable sql debugging to trace the caller."
            _logger.warning(msg)
            self._close()

    def execute(
        self,
        query: str | bytes | SQL | _sql.Composable,
        params: tuple | list | dict | None = None,
        log_exceptions: bool = True,
        prepare: bool | None = None,
    ) -> None:

        self._before_statement()

        if isinstance(query, SQL):
            if params is not None:
                raise ValueError(
                    "Unexpected parameters combined with a SQL query object"
                )
            query, params = query.code, query.params
        else:
            if isinstance(query, _sql.Composable):
                query = query.as_string(self._cnx)
            if params and not isinstance(params, (tuple, list, dict)):
                raise ValueError(
                    f"SQL query parameters should be a tuple, list or dict; got {params!r}"
                )

        if isinstance(query, bytes):
            try:
                qs = query.decode()
            except UnicodeDecodeError:
                qs = ""
        else:
            qs = query
        ddl_kw = _ddl_keyword(qs)
        is_ddl = ddl_kw is not None

        if params and is_ddl:
            query = _inline_ddl_params(qs, params, self._cnx)
            params = None

        if is_ddl and prepare is None:
            prepare = False

        debug = _logger.isEnabledFor(logging.DEBUG)
        hooks = getattr(self._thread, "query_hooks", None)
        start = real_time() if hooks else 0.0
        obj = self._obj
        t0 = monotonic()
        try:
            obj.execute(query, params, prepare=prepare)
        except Exception as e:
            if log_exceptions:
                _log_sql_error(e, query)
            raise
        finally:
            delay = monotonic() - t0
            if debug:
                _logger.debug(
                    "[%.3f ms] query: %s",
                    1000 * delay,
                    self._format(query, params),
                )

        if _changes_schema(qs, ddl_kw):
            self._invalidate_caches_after_ddl()
        elif ddl_kw is None and _is_rollback_to_savepoint(qs):
            # A raw ``ROLLBACK TO SAVEPOINT`` (issued as SQL rather than through
            # cr.savepoint()) undoes DDL since the savepoint; re-arm the hook the
            # Savepoint class would have fired, so transaction-scoped catalog
            # facts do not outlive the schema they describe.
            self._on_rollback_to_savepoint()

        self._record_metrics(
            delay, query=query, params=params, start=start, hooks=hooks
        )

        if debug:
            query_type, table = categorize_query(qs)
            self._record_sql_log(query_type, table, delay)

    def discard_cached_plans(self) -> None:
        """Drop the schema-dependent caches attached to this connection / db."""
        try:
            self._cnx._prepared.clear()
        except AttributeError:
            _logger.warning(
                "psycopg no longer exposes Connection._prepared.clear(); "
                "auto-prepare is off for the rest of this cursor's life "
                "(restored when the connection returns to the pool). "
                "Re-check odoo.db.cursor against the installed psycopg.",
            )
            self._cnx.prepare_threshold = None
            self._cnx.execute("DEALLOCATE ALL")
        self._schema_cache.clear_catalog_facts()

    def _on_rollback_to_savepoint(self) -> None:
        """Drop catalog facts a partial rollback may have invalidated.

        ``ROLLBACK TO SAVEPOINT`` can undo DDL executed inside the savepoint,
        including DDL whose *post*-change types this cursor already read and
        memoized (the DDL cleared the cache, then the lookup repopulated it).
        Those entries now describe a schema that was rolled back, so a later
        binary ``copy_from`` would encode with types the table no longer has.
        Unlike ``commit``/``rollback`` this does not end the transaction, so the
        ``ROW EXCLUSIVE`` locks stay held — only the facts are dropped, and the
        next lookup re-reads them under the lock already in hand.
        """
        self._schema_cache.clear()

    def _invalidate_caches_after_ddl(self) -> None:
        """Drop the caches a schema-changing DDL invalidates on this connection.

        Other workers are cleared via registry signalling, but not the one that
        ran the DDL — same clearing logic, see :meth:`discard_cached_plans`.
        """
        self.discard_cached_plans()

    def executemany(
        self,
        query: str | SQL | _sql.Composable,
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

        .. note::
            **Query accounting.**  This records **N** queries for N parameter
            sets — one round-trip, but N statements for the server to plan and
            execute.  :meth:`copy_from` records **1** for an N-row COPY, which
            really is one statement.  See that method for why the counters
            measure requested SQL work rather than packets.
        """
        self._before_statement()

        if isinstance(query, SQL):
            if query.params:
                raise ValueError(
                    "executemany does not support SQL objects with embedded "
                    "params; pass the per-row params via params_seq instead."
                )
            query = query.code
        elif isinstance(query, _sql.Composable):
            query = query.as_string(self._cnx)

        if not hasattr(params_seq, "__len__"):
            params_seq = list(params_seq)
        if not params_seq:
            return

        hooks = getattr(self._thread, "query_hooks", None)
        start = real_time() if hooks else 0.0
        obj = self._obj
        t0 = monotonic()
        try:
            obj.executemany(query, params_seq, returning=returning)
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
                    len(params_seq),
                    query,
                )

        self._record_metrics(
            delay, len(params_seq), query=query, start=start, hooks=hooks
        )

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
        if not self._closed:
            self._close()

    def _close(self) -> None:
        try:
            self.cache.clear()

            self.print_log()

            self._obj.close()
        finally:
            self._closed = True

            del self._obj

            keep_in_pool = True
            try:
                self._do_rollback()
            except Exception:
                _logger.debug("Failed to roll back on cursor close", exc_info=True)
                keep_in_pool = self._connection_is_clean()
            finally:
                self.__pool.give_back(self._cnx, keep_in_pool=keep_in_pool)

    def _connection_is_clean(self) -> bool:
        """True when the connection has no transaction open, so it may be pooled.

        ``transaction_status`` is a libpq-local field (no round-trip).  Only
        ``IDLE`` is accepted: ``INTRANS``/``INERROR`` mean the ROLLBACK did not
        happen and ``UNKNOWN`` means the socket is gone, both of which make the
        connection unsafe to hand to the next borrower.  Any failure reading it
        (a closed connection) answers "not clean".
        """
        try:
            return self._cnx.info.transaction_status == _TX_IDLE
        except Exception:
            return False

    def commit(self) -> None:
        """Perform an SQL `COMMIT`"""
        if self._closed:
            raise psycopg.InterfaceError("Cursor already closed")
        if self._savepoint_depth:
            raise RuntimeError(
                "Cannot commit inside a savepoint! "
                "This would corrupt the savepoint's rollback state."
            )
        self.flush()
        self._cnx.commit()
        self.clear()
        self._schema_cache.clear()
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
        if self._closed:
            raise psycopg.InterfaceError("Cursor already closed")
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
        try:
            self.prerollback.run()
        finally:
            self._cnx.rollback()
            self._schema_cache.clear()
        self._now = None
        self.postrollback.run()

    def __getattr__(self, name: str) -> Any:
        """Refuse anything outside the Odoo cursor API.

        This used to warn and then forward to the underlying psycopg cursor,
        which meant an unknown attribute silently *worked* — and a wrapper
        cursor could reach raw psycopg through two layers of ``__getattr__``
        without any of the bookkeeping in between.  That is exactly how the
        ``TestCursor`` bulk-write savepoint bypass survived: ``copy_from`` on a
        test cursor forwarded to ``TestCursor._cursor``, then past this method,
        and wrote outside the savepoint.  A ``DeprecationWarning`` is invisible
        in a passing test run; an ``AttributeError`` is not.

        Measured before switching: across 13,680 non-test modules in core,
        base, enterprise, agromarin and design-themes there is no caller that
        relies on the forwarding, and a full ``base`` run emits the warning
        exactly zero times.  Code that genuinely needs psycopg's own surface
        should say so — ``cr._obj.<name>`` — rather than have it appear by
        accident.
        """
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        if self._closed:
            msg = "Cursor already closed"
            raise psycopg.InterfaceError(msg)
        raise AttributeError(
            f"Cursor.{name} is not part of the Odoo cursor API. "
            f"Add explicit forwarding in cursor.py, or reach psycopg deliberately "
            f"with cr._obj.{name}."
        )

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
    from .bulk import _CursorInternals

    def _assert_cursor_satisfies_bulk_host(_c: Cursor) -> _CursorInternals:
        return _c

    from .metrics import _MetricsHost

    def _assert_cursor_satisfies_metrics_host(_c: Cursor) -> _MetricsHost:
        return _c
