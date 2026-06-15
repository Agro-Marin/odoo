import itertools
import logging
import os
import re as _re
import threading
import warnings
from collections.abc import Generator, Iterable
from contextlib import contextmanager, suppress
from contextlib import nullcontext as _nullcontext
from datetime import datetime, timedelta
from decimal import Decimal as _Decimal
from inspect import currentframe
from typing import TYPE_CHECKING, Any, Self

import psycopg
from psycopg import IsolationLevel
from psycopg import sql as _sql

from odoo import tools
from odoo.libs.func import frame_codeinfo, reset_cached_properties
from odoo.tools import SQL
from odoo.tools.misc import Callbacks, real_time

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

# Global SQL query counter (used for debugging/profiling).
# Intentionally a bare int — not atomic.  Under --workers=0 (threaded),
# concurrent += can lose counts.  This is acceptable: the counter is
# approximate by design and adding a lock would slow every query for
# debug-only data.  In forked mode each worker has its own copy.
sql_counter: int = 0

# Cache: (dbname, table) → sequence name for the id column.
# Populated lazily by Cursor.copy_from() when returning_ids=True.
# NB: keys MUST include the database name — one process serves several
# databases whose same-named tables may have diverging schemas (staggered
# module versions), and a stale cross-DB entry poisons every subsequent
# bulk create() on that table until restart.
_id_sequence_cache: dict[tuple[str, str], str] = {}

# Monotonic counter for savepoint names (thread-safe via CPython's GIL).
_savepoint_counter = itertools.count()

# Cache: (dbname, table, columns) → list of PostgreSQL type names.
# Used by binary COPY to provide exact types via set_types().
# Same dbname-keying requirement as _id_sequence_cache above.
_column_type_cache: dict[tuple[str, str, tuple[str, ...]], list[str]] = {}


def _clear_schema_caches(dbname: str | None = None) -> None:
    """Drop cached schema lookups (column types, id sequences).

    :param dbname: only drop entries for this database; ``None`` drops all.
    """
    for cache in (_column_type_cache, _id_sequence_cache):
        if dbname is None:
            cache.clear()
        else:
            # pop(), not del: two threads draining the same database (registry
            # signalling + a concurrent drop) snapshot the same keys, and the
            # loser of the race would KeyError on an already-removed key.
            # list(cache) snapshots the keys BEFORE filtering: iterating the
            # live dict while another thread (copy_from populating the cache)
            # inserts raises "dictionary changed size during iteration".
            for key in [k for k in list(cache) if k[0] == dbname]:
                cache.pop(key, None)


# DDL statements that must use client-side parameter formatting.
# PostgreSQL's extended query protocol only accepts $N parameters in
# value positions (WHERE, INSERT VALUES, etc.).  DDL structural
# positions (column types, constraints, comments, sequence options)
# reject parameterized values outright.
#
# Intentionally excluded: TRUNCATE, SET, VACUUM, ANALYZE, REINDEX,
# CLUSTER, LOCK — these also reject server-side parameters, but Odoo
# never parameterizes them.  If a future caller does, extend BOTH the
# regex AND ``_DDL_PREFIXES`` (the 2-char prefix gate below).
# Match the DDL keyword even when preceded by SQL comments (line ``-- ...``
# or block ``/* ... */``).  Without the comment-skip prefix a statement like
# ``-- migrate\nCREATE TABLE ...`` slips past detection: the auto-prepared
# statement cache is never invalidated and a later ``SELECT *`` raises
# ``cached plan must not change result type`` (verified reproducible).
_RE_DDL = _re.compile(
    r"^\s*(?:(?:--[^\n]*\n|/\*.*?\*/)\s*)*"
    r"(?:CREATE|ALTER|DROP|COMMENT|GRANT|REVOKE|DO)\b",
    _re.IGNORECASE | _re.DOTALL,
)
# First two chars of the statement for fast prefix filtering — avoids the regex
# on the 99% of queries that are SELECT/INSERT/UPDATE/DELETE.  ``--`` and ``/*``
# are included so comment-prefixed DDL still reaches the regex; comment-prefixed
# non-DDL is rare, so the extra regex runs are negligible.
_DDL_PREFIXES = frozenset(("CR", "AL", "DR", "CO", "GR", "RE", "DO", "--", "/*"))

# Recoverable transaction errors: the request/retry machinery (http._serve's
# read-only retry, the ORM's optimistic-concurrency retry loop) catches these
# and retries, so they are an EXPECTED part of normal operation under
# contention.  Logging them at ERROR ("bad query") floods the log with false
# faults on every retry.  Demote to WARNING — observable, but not masquerading
# as a defect.  Anything genuinely fatal still hits the ERROR branch.
_RECOVERABLE_SQL_ERRORS: tuple[type[BaseException], ...] = (
    psycopg.errors.ReadOnlySqlTransaction,  # 25006 — caller retries r/w
    psycopg.errors.SerializationFailure,  # 40001 — MVCC, caller retries
    psycopg.errors.DeadlockDetected,  # 40P01 — caller retries
    psycopg.errors.LockNotAvailable,  # 55P03 — NOWAIT/timeout, caller handles
)


def _find_value_markers(query: str) -> list[int]:
    """Return positions of real ``%s`` placeholders in *query*.

    Skips ``%%`` escape sequences, so a literal like ``LIKE 'a%%s'`` is not
    mistaken for a placeholder (naive ``str.count``/``str.replace`` both
    match the ``%s`` inside ``%%s`` and mangle the query).
    """
    out = []
    i, n = 0, len(query)
    while i < n - 1:
        if query[i] == "%":
            if query[i + 1] == "s":
                out.append(i)
            # skip the full token: '%%' escape, '%s' marker, or '%x' junk
            i += 2
        else:
            i += 1
    return out


def _log_sql_error(exc: Exception, query: Any) -> None:
    """Log a failed SQL statement at a level that matches its recoverability.

    Recoverable errors (read-only retry, MVCC serialization, deadlock,
    lock-not-available) are expected under contention and retried by the
    caller, so they log at WARNING — observable without masquerading as a
    fault.  Everything else is a genuine defect and logs at ERROR.

    Shared by :meth:`Cursor.execute` and :meth:`Cursor.executemany`, whose
    error handling was previously byte-for-byte identical.

    :param exc: the exception raised by the psycopg call.
    :param query: the executed query string (for the log message).
    """
    if isinstance(exc, _RECOVERABLE_SQL_ERRORS):
        _logger.warning(
            "recoverable SQL error (caller may retry): %s: %s",
            type(exc).__name__,
            query,
        )
    else:
        _logger.error("bad query: %s\nERROR: %s", query, exc)


def _inline_ddl_params(qs: str, params: tuple | list | dict, ctx: Any) -> str:
    """Return *qs* with *params* spliced in as client-side quoted literals.

    DDL structural positions (column types, ``DEFAULT`` expressions,
    ``COMMENT`` bodies, sequence options, …) reject server-side ``$N``
    parameters, so the values must be quoted client-side via
    :func:`psycopg.sql.quote` and inlined into the statement text.

    :param qs: the DDL statement text with ``%s`` / ``%(name)s`` markers.
    :param params: positional (tuple/list) or named (dict) parameters.
    :param ctx: a psycopg adapter context (connection/cursor) for ``quote``.
    :return: the statement with every marker replaced by a quoted literal.
    :raises ValueError: if the positional marker count differs from *params*.
    """
    # psycopg.sql.quote already returns str — no wrapper needed.
    if isinstance(params, dict):
        # %(name)s style: Python formatting is the only practical
        # substitution.  Documented caveat — a literal % in a dict-param
        # DDL body must be written %% by the caller.
        return qs % {k: _sql.quote(v, ctx) for k, v in params.items()}
    # Splice quoted values at the real %s markers rather than using
    # ``qs % (...)``, which misreads a literal % in the DDL body
    # (e.g. COMMENT ... IS '50% done') as a format spec and raises.
    # _find_value_markers is %%-escape aware; literal %% is then
    # unescaped to % in the surrounding segments to match what the
    # old %-formatting did.
    markers = _find_value_markers(qs)
    if len(markers) != len(params):
        raise ValueError(
            f"DDL parameter count mismatch: {len(markers)} '%s' "
            f"marker(s) but {len(params)} param(s)"
        )
    out, prev = [], 0
    # lengths already validated equal above; strict=True is belt-and-braces
    for pos, value in zip(markers, params, strict=True):
        out.append(qs[prev:pos].replace("%%", "%"))
        out.append(_sql.quote(value, ctx))
        prev = pos + 2
    out.append(qs[prev:].replace("%%", "%"))
    return "".join(out)


class Savepoint:
    """Reifies an active breakpoint, allows :meth:`BaseCursor.savepoint` users
    to internally rollback the savepoint (as many times as they want) without
    having to implement their own savepointing, or triggering exceptions.

    Should normally be created using :meth:`BaseCursor.savepoint` rather than
    directly.

    The savepoint will be rolled back on unsuccessful context exits
    (exceptions). It will be released ("committed") on successful context exit.
    The savepoint object can be wrapped in ``contextlib.closing`` to
    unconditionally roll it back.

    The savepoint can also safely be explicitly closed during context body. This
    will rollback by default.

    :param BaseCursor cr: the cursor to execute the `SAVEPOINT` queries on
    """

    __slots__ = ("_cr", "closed", "name")

    def __init__(self, cr: _CursorProtocol):
        self.name = f"sp{next(_savepoint_counter)}"
        self._cr = cr
        self.closed: bool = False
        # NB: f-string SQL is safe here — name is always "sp{int}" from our
        # own counter, never user input.  psycopg.sql.Identifier would add
        # overhead (quote + adapt) for zero security benefit.
        cr.execute(f'SAVEPOINT "{self.name}"')

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        self.close(rollback=exc_type is not None)

    def close(self, *, rollback: bool = True) -> None:
        if not self.closed:
            self._close(rollback)

    def rollback(self) -> None:
        self._cr.execute(f'ROLLBACK TO SAVEPOINT "{self.name}"')

    def _close(self, rollback: bool) -> None:
        if rollback:
            self.rollback()
        self._cr.execute(f'RELEASE SAVEPOINT "{self.name}"')
        self.closed = True


class _FlushingSavepoint(Savepoint):
    """Savepoint that flushes and saves ORM state for correct rollback.

    On creation, flushes pending writes and snapshots the transaction's
    ``default_env`` and ``registry_sequence``.  On rollback, restores both
    so the ORM view of the world matches the database state after
    ``ROLLBACK TO SAVEPOINT``.
    """

    __slots__ = ("_saved_default_env", "_saved_registry_seq")

    def __init__(self, cr: BaseCursor) -> None:
        cr.flush()
        # Save ORM state that must survive rollback.
        # Cache/compute state is ephemeral — clear() handles it.
        # default_env and registry_sequence are the only durable state.
        txn = cr.transaction
        self._saved_default_env = txn.default_env if txn else None
        self._saved_registry_seq = txn.registry.registry_sequence if txn else -1
        # Increment depth only after the SAVEPOINT SQL succeeds — otherwise
        # a failing connection leaves the counter +1 with nothing to roll
        # back, wedging every subsequent commit/rollback on the `assert
        # savepoint_depth == 0` check.
        super().__init__(cr)
        if txn is not None:
            txn.savepoint_depth += 1

    def rollback(self) -> None:
        cr = self._cr
        assert isinstance(cr, BaseCursor)
        super().rollback()  # SQL ROLLBACK TO SAVEPOINT first
        txn = cr.transaction
        if txn is None:
            return
        # Restore default_env to pre-savepoint value
        txn.default_env = self._saved_default_env
        # If registry was reloaded inside the savepoint, full reset
        if txn.registry.registry_sequence != self._saved_registry_seq:
            txn.reset()
        else:
            txn.clear()
            for env in txn.envs:
                reset_cached_properties(env)

    def _close(self, rollback: bool) -> None:
        cr = self._cr
        assert isinstance(cr, BaseCursor)
        try:
            try:
                if not rollback:
                    cr.flush()
            except Exception:
                rollback = True
                raise
            finally:
                super()._close(rollback)
        finally:
            # Balance __init__'s +=1 unconditionally.  If this decrement
            # is skipped after a RELEASE/ROLLBACK TO SAVEPOINT failure,
            # savepoint_depth stays +1 and every subsequent commit or
            # rollback asserts on ``savepoint_depth == 0``, wedging the
            # cursor for its remaining lifetime.
            if cr.transaction is not None:
                cr.transaction.savepoint_depth -= 1


# _CursorProtocol declares the available methods and type information,
# at runtime, it is just an `object`
class BaseCursor(_CursorProtocol):
    """Base class for cursors that manage pre/post commit hooks."""

    BATCH_SIZE = 1000  # max array size per = ANY() query — keeps planner efficient

    transaction: Transaction | None
    cache: dict[Any, Any]
    dbname: str

    def __init__(self) -> None:
        self.precommit = Callbacks()
        self.postcommit = Callbacks()
        self.prerollback = Callbacks()
        self.postrollback = Callbacks()
        self._now: datetime | None = None
        self.cache = {}
        # By default a cursor has no transaction object.  A transaction object
        # for managing environments is instantiated by registry.cursor().  It
        # is not done here in order to avoid cyclic module dependencies.
        self.transaction = None

    def flush(self) -> None:
        """Flush the current transaction, and run precommit hooks."""
        # In case some pre-commit added another pre-commit or triggered changes
        # in the ORM, we must flush and run it again.
        for _ in range(10):  # limit number of iterations
            if self.transaction is not None:
                self.transaction.flush()
            if not self.precommit:
                break
            self.precommit.run()
        else:
            # Raise, don't warn: callers (commit()) would otherwise COMMIT
            # and clear() the still-pending precommit hooks — silently
            # dropping whatever work they were supposed to do.
            raise RuntimeError(
                "flush() did not converge after 10 iterations: precommit "
                "hooks keep triggering new ORM changes; committing now "
                "would silently drop pending hooks."
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
        relevant hooks.
        """
        if flush:
            return _FlushingSavepoint(self)
        else:
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


class Cursor(BaseCursor):
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

    def __init__(self, pool: ConnectionPool, dbname: str, dsn: dict):
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

        self._cnx: psycopg.Connection = pool.borrow(dsn)
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
            self._closed = False  # only after all setup succeeds
        except Exception:
            # If _obj was created before the setter failed, close it before
            # returning the connection — psycopg_pool's reset() only rolls
            # back the transaction, it does not close open cursors.
            obj = getattr(self, "_obj", None)
            if obj is not None:
                with suppress(Exception):
                    obj.close()
            pool.give_back(self._cnx)
            raise

        if (
            os.getenv("ODOO_FAKETIME_TEST_MODE")
            and self.dbname in tools.config["db_name"]
        ):
            self.execute("SET search_path = public, pg_catalog;")
            self.commit()  # ensure that the search_path remains after a rollback

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

    def dictfetchmany(self, size: int) -> list[dict[str, Any]]:
        rows = self._obj.fetchmany(size)
        if not rows:
            return []
        if _rows_to_dicts is not None:
            return _rows_to_dicts(self._col_names(), rows)
        cols = self._col_names()
        return [dict(zip(cols, row, strict=True)) for row in rows]

    def dictfetchall(self) -> list[dict[str, Any]]:
        rows = self._obj.fetchall()
        if not rows:
            return []
        if _rows_to_dicts is not None:
            return _rows_to_dicts(self._col_names(), rows)
        cols = self._col_names()
        return [dict(zip(cols, row, strict=True)) for row in rows]

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
        self,
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

    def _record_sql_log(self, query_type: str, table: str | None, delay: float) -> None:
        """Accumulate per-table from/into timing stats (DEBUG-only).

        Shared by :meth:`execute` and :meth:`copy_from`, whose stats
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

        # Detect DDL once up-front. The prefix check (2-char compare against
        # a frozenset) avoids the regex on the 99% of queries that are
        # SELECT/INSERT/UPDATE/DELETE.  The flag is consumed twice: before
        # execute (DDL structural positions reject server-side parameters,
        # so params must be inlined client-side) and after (CREATE/ALTER
        # change schema, so psycopg3's auto-prepared statement cache must
        # be invalidated).
        qs = query if isinstance(query, str) else str(query)
        # Slice before lstrip: a bare ``qs.lstrip()`` copies the ENTIRE query
        # to read 2 chars whenever it has leading whitespace (Odoo's triple-
        # quoted SQL nearly always does).  64 chars is far more than any real
        # leading-whitespace run, so the prefix gate is unchanged.
        c = qs[:64].lstrip()[:2].upper()
        is_ddl = c in _DDL_PREFIXES and _RE_DDL.match(qs) is not None

        if params and is_ddl:
            # DDL rejects server-side $N parameters — inline them client-side
            # as quoted literals (see _inline_ddl_params for the why/how).
            query = _inline_ddl_params(qs, params, self._cnx)
            params = None

        start = real_time()
        try:
            self._obj.execute(query, params)
        except Exception as e:
            if log_exceptions:
                _log_sql_error(e, query)
            raise
        finally:
            delay = real_time() - start
            if _logger.isEnabledFor(logging.DEBUG):
                _logger.debug(
                    "[%.3f ms] query: %s",
                    1000 * delay,
                    self._format(query, params),
                )

        if is_ddl:
            # psycopg3's PrepareManager natively handles DROP/ROLLBACK, but
            # CREATE/ALTER also change schema — making cached plans for
            # SELECT * queries stale ("cached plan must not change result type").
            # Private API: psycopg 3.x has no public method to invalidate
            # the auto-prepared statement cache.  _prepared.clear() queues a
            # DEALLOCATE ALL on the next execute().  If a future psycopg
            # removes the attribute, disable auto-prepare on this connection
            # instead (covers the rest of its max_lifetime window).
            try:
                self._cnx._prepared.clear()
            except AttributeError:
                self._cnx.prepare_threshold = None

        self._record_metrics(delay, query=query, params=params, start=start)

        # advanced stats (see _record_sql_log; copy_from shares the same path)
        if _logger.isEnabledFor(logging.DEBUG):
            query_type, table = categorize_query(str(query))
            self._record_sql_log(query_type, table, delay)

    def execute_values(
        self,
        query: str | _sql.Composable,
        argslist: list[Any],
        template: str | None = None,
        page_size: int = 100,
        fetch: bool = False,
    ) -> list[tuple[Any, ...]] | None:
        """Execute a query with multiple parameter sets using VALUES clause.

        Builds a single query with multiple VALUES rows per batch, useful for
        patterns like ``UPDATE ... FROM (VALUES %s) AS source(...)``.

        For simple multi-row INSERTs, prefer :meth:`executemany` which
        auto-pipelines for better performance.
        """
        if isinstance(query, _sql.Composable):
            query = query.as_string(self._obj)
        # Reject non-positive page_size BEFORE touching argslist — page_size=0
        # later crashes range() with a cryptic "arg 3 must not be zero", and
        # page_size<0 produces an empty range() that silently drops every
        # row the caller asked to insert (confirmed data-loss path).
        if page_size <= 0:
            raise ValueError(f"execute_values page_size must be >= 1, got {page_size}")
        if not argslist:
            return [] if fetch else None
        # The query must have exactly one real `%s` marker — the position
        # where the batched VALUES row-list gets expanded.  Any other `%s`
        # would produce malformed SQL with a parameter-count mismatch at
        # best.  Markers are located with an escape-aware scan: `%%`
        # sequences (literal percent, e.g. LIKE 'a%%s') are NOT markers.
        markers = _find_value_markers(query)
        if len(markers) != 1:
            raise ValueError(
                f"execute_values requires exactly one '%s' marker in the "
                f"query (for the VALUES list); got {len(markers)}."
            )
        marker_pos = markers[0]
        results = []
        batches = range(0, len(argslist), page_size)
        # Pipeline multi-batch non-fetch executions for single round-trip
        use_pipeline = len(argslist) > page_size and not fetch
        ctx = self._cnx.pipeline() if use_pipeline else _nullcontext()
        with ctx:
            for i in batches:
                batch = argslist[i : i + page_size]
                placeholders = []
                params = []
                for row in batch:
                    if template:
                        placeholders.append(template)
                    elif isinstance(row, (list, tuple)):
                        placeholders.append("(" + ", ".join(["%s"] * len(row)) + ")")
                    else:
                        placeholders.append("(%s)")
                    if isinstance(row, (list, tuple)):
                        params.extend(row)
                    else:
                        params.append(row)
                full_query = (
                    f"{query[:marker_pos]}"
                    f"{', '.join(placeholders)}"
                    f"{query[marker_pos + 2 :]}"
                )
                self.execute(full_query, params)
                if fetch:
                    results.extend(self.fetchall())
        return results if fetch else None

    def executemany(
        self,
        query: str | SQL,
        params_seq: Iterable[tuple | list | dict],
        returning: bool = False,
    ) -> None:
        """Execute a query with multiple parameter sets using pipeline mode.

        psycopg3's executemany automatically batches all statements in a
        single network round-trip on PostgreSQL 14+, avoiding the overhead
        of individual execute() calls.

        :param query: SQL query with ``%s`` placeholders
        :param params_seq: Sequence of parameter tuples/lists
        :param returning: If True, collect RETURNING results per statement.
            Use ``fetchall()`` + ``nextset()`` loop to read all result sets.
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

        start = real_time()
        try:
            self._obj.executemany(query, params_seq, returning=returning)
        except Exception as e:
            _log_sql_error(e, query)
            raise
        finally:
            delay = real_time() - start
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
        """
        with self._cnx.pipeline():
            yield

    def copy_from(
        self,
        table: str,
        columns: list[str],
        rows,
        *,
        returning_ids: bool = False,
        binary: bool = False,
        on_error: str | None = None,
    ) -> list[int] | None:
        """Bulk insert rows using PostgreSQL COPY protocol.

        Streams rows via COPY FROM STDIN, bypassing SQL parsing and planning
        overhead.  2-5x faster than multi-row INSERT for large batches.

        All Python types (Json, datetime, None, etc.) are adapted automatically
        by psycopg3's Transformer — the same adapter system used by execute().

        :param table: Target table name
        :param columns: List of column names
        :param rows: Iterable of tuples/lists matching columns
        :param returning_ids: If True, pre-generate IDs via the table's
            serial sequence and return them.  ``'id'`` is prepended to
            *columns* automatically.

            .. warning::
                When ``returning_ids=True``, *rows* is materialized into
                a list to count it before calling ``nextval()``.  For
                very large imports (millions of rows), this defeats
                streaming and may exhaust memory.  For memory-bounded
                imports that still need IDs, chunk the input externally
                or use ``returning_ids=False`` plus batched
                ``INSERT ... RETURNING id``.
        :param binary: If True, use binary COPY format (faster but requires
            exact type matching via ``set_types()``). Column types are looked
            up from ``pg_attribute`` and cached per table.
        :param on_error: Error handling for data type conversion errors
            (PG17+, text/CSV mode only).  ``'ignore'`` skips malformed rows
            instead of aborting the entire operation.  Useful for fault-
            tolerant data imports.  Rejected with ``binary=True`` (the
            option has no effect in binary mode) or ``returning_ids=True``
            (the pre-allocated sequence IDs cannot be reconciled with
            server-side row skipping — use batched INSERT … RETURNING).
        :return: list of generated IDs when *returning_ids* is True, else None
        """
        if on_error is not None and on_error not in ("ignore", "stop"):
            # Whitelist: on_error is interpolated into the COPY options
            # clause below — never let an arbitrary string through.
            raise ValueError(
                f"copy_from: invalid on_error {on_error!r}; "
                f"allowed values: 'ignore', 'stop'."
            )
        if on_error and binary:
            raise ValueError(
                "copy_from: on_error is not supported with binary=True; "
                "binary COPY has no ON_ERROR clause."
            )
        if on_error == "ignore" and returning_ids:
            raise ValueError(
                "copy_from: on_error='ignore' is incompatible with "
                "returning_ids=True — pre-allocated sequence IDs cannot be "
                "reconciled with rows silently dropped by the server. "
                "Use batched INSERT ... RETURNING id for fault-tolerant "
                "inserts that need IDs."
            )
        if returning_ids:
            rows = list(rows)
            count = len(rows)
            if count == 0:
                return []
            # Look up the sequence for the id column (cached).
            # pg_get_serial_sequence only finds sequences *owned* by the
            # column, but _inherits child tables share the parent's
            # sequence.  We fall back to the pg_depend catalog which finds
            # the sequence referenced by the column's DEFAULT expression.
            seq_name = _id_sequence_cache.get((self.dbname, table))
            if seq_name is None:
                self.execute(SQL("SELECT pg_get_serial_sequence(%s, 'id')", table))
                (seq_name,) = self.fetchone()
                if seq_name is None:
                    # Shared sequence (e.g. _inherits): find via pg_depend
                    self.execute(
                        SQL(
                            """SELECT s.oid::regclass::text
                        FROM pg_attrdef ad
                        JOIN pg_class t ON t.oid = ad.adrelid
                        JOIN pg_attribute a ON a.attrelid = t.oid
                            AND a.attnum = ad.adnum
                        JOIN pg_depend d ON d.objid = ad.oid
                            AND d.classid = 'pg_attrdef'::regclass
                            AND d.refclassid = 'pg_class'::regclass
                        JOIN pg_class s ON s.oid = d.refobjid
                            AND s.relkind = 'S'
                        WHERE t.relname = %s AND a.attname = 'id'
                        LIMIT 1""",
                            table,
                        )
                    )
                    row = self.fetchone()
                    if not row or not row[0]:
                        raise ValueError(f"No serial sequence found for {table}.id")
                    seq_name = row[0]
                _id_sequence_cache[self.dbname, table] = seq_name
            # Pre-generate IDs from the sequence
            self.execute(
                SQL(
                    "SELECT nextval(%s::regclass) FROM generate_series(1, %s)",
                    seq_name,
                    count,
                )
            )
            ids = [row[0] for row in self.fetchall()]
            columns = ["id", *columns]
            # strict: nextval() generated exactly len(rows) ids — a mismatch
            # is a logic error and must not silently truncate the batch.
            rows = [((id_, *tuple(row))) for id_, row in zip(ids, rows, strict=True)]
        else:
            ids = None

        cols_sql = _sql.SQL(", ").join(map(_sql.Identifier, columns))
        # Build COPY options: FORMAT and ON_ERROR are independent.
        # ON_ERROR ignore (PG17) skips rows with type conversion errors
        # in text/CSV mode; it has no effect in binary mode.
        copy_opts = []
        if binary:
            copy_opts.append("FORMAT BINARY")
        if on_error and not binary:
            copy_opts.append(f"ON_ERROR {on_error}")
        if copy_opts:
            opts_sql = _sql.SQL(" ({})".format(", ".join(copy_opts)))
        else:
            opts_sql = _sql.SQL("")
        copy_stmt = _sql.SQL("COPY {} ({}) FROM STDIN{}").format(
            _sql.Identifier(table),
            cols_sql,
            opts_sql,
        )

        # Look up column types BEFORE entering the COPY context.
        # Inside `with self._obj.copy(...)`, the connection is in COPY
        # mode and cannot execute other queries (would block forever).
        col_types = self._get_column_types(table, columns) if binary else None

        # psycopg3's NumericBinaryDumper rejects Python float for PG
        # "numeric" columns — it requires Decimal.  Pre-compute which
        # column indices need float→Decimal conversion (Monetary fields
        # and Float-with-digits both map to "numeric").
        if col_types:
            _numeric_idxs = frozenset(
                i for i, t in enumerate(col_types) if t == "numeric"
            )
        else:
            _numeric_idxs = None

        start = real_time()
        row_count = 0
        try:
            with self._obj.copy(copy_stmt) as copy:
                if col_types:
                    copy.set_types(col_types)
                for row in rows:
                    if _numeric_idxs:
                        # Convert ONLY the numeric columns: psycopg3's binary
                        # NumericDumper rejects Python float for PG "numeric"
                        # (it wants Decimal).  Rebuilding the whole tuple per
                        # row — enumerate plus an ``i in frozenset`` test on
                        # every column — is ~2x slower for wide tables (measured
                        # ~0.8s per 1M rows on a 20-col row); mutate a list copy
                        # at the known indices instead.  isinstance (not
                        # ``type is float``) preserves the original semantics for
                        # float subclasses.
                        row = list(row)
                        for i in _numeric_idxs:
                            v = row[i]
                            if isinstance(v, float):
                                row[i] = _Decimal(str(v))
                    copy.write_row(row)
                    row_count += 1
        except Exception as e:
            _logger.error("bad COPY: %s\nERROR: %s", copy_stmt.as_string(self._obj), e)
            raise
        finally:
            delay = real_time() - start
            if _logger.isEnabledFor(logging.DEBUG):
                _logger.debug(
                    "[%.3f ms] COPY %s (%d rows)",
                    1000 * delay,
                    table,
                    row_count,
                )

        # Render copy_stmt to text only when a profiler query hook will read it.
        # copy_from is a hot path (imports, module installs); building the SQL
        # string unconditionally wasted a full render on every bulk insert in
        # the common no-hook case.  _record_metrics only forwards `query` to
        # thread query_hooks, so None is harmless when none are installed.
        metrics_query = (
            copy_stmt.as_string(self._obj)
            if getattr(self._thread, "query_hooks", None)
            else None
        )
        self._record_metrics(delay, query=metrics_query, start=start)

        if _logger.isEnabledFor(logging.DEBUG):
            self._record_sql_log("into", table, delay)

        return ids

    def _get_column_types(self, table: str, columns: list[str]) -> list[str]:
        """Look up PostgreSQL base type names for binary COPY.

        Results are cached in ``_column_type_cache`` since schema doesn't
        change during a session.
        """
        key = (self.dbname, table, tuple(columns))
        types = _column_type_cache.get(key)
        if types is None:
            self.execute(
                SQL(
                    # Resolve the table via ::regclass so search_path is honored
                    # (TEMP tables live in pg_temp_N, never current_schema).  This
                    # matches the pg_get_serial_sequence(table, 'id') resolution
                    # used for returning_ids — the two lookups must agree, or
                    # binary COPY into a temp table raises "column not found".
                    """SELECT a.attname, t.typname
                    FROM pg_attribute a
                    JOIN pg_type t ON a.atttypid = t.oid
                    WHERE a.attrelid = %s::regclass
                      AND a.attnum > 0 AND NOT a.attisdropped
                      AND a.attname = ANY(%s)""",
                    table,
                    list(columns),
                )
            )
            type_map = dict(self.fetchall())
            missing = [col for col in columns if col not in type_map]
            if missing:
                raise ValueError(
                    f"copy_from: column(s) {missing} not found in table "
                    f"{table!r} (current_schema)"
                )
            types = [type_map[col] for col in columns]
            _column_type_cache[key] = types
        return types

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
                    sqllog.items(), key=lambda k: k[1]
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

    def close(self) -> None:
        # Intentionally test self._closed, NOT self.closed.  The property
        # also returns True when _cnx.closed flips (network failure, peer
        # drop).  If we short-circuit on it, _close() never runs and the
        # semaphore slot plus self._obj leak for the life of the process.
        if not self._closed:
            self._close()

    def _close(self) -> None:
        if not self._obj:
            return

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
        # inside a savepoint corrupts the savepoint's rollback state.
        if self.transaction is not None and self.transaction.savepoint_depth:
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
        # Explicit check (not assert): must survive ``python -O``.
        if self.transaction is not None and self.transaction.savepoint_depth:
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
