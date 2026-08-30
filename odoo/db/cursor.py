import logging
import os
import threading
from collections.abc import Collection, Generator, Iterable
from contextlib import ExitStack, contextmanager, suppress
from datetime import datetime
from inspect import currentframe
from time import monotonic
from typing import TYPE_CHECKING, Any, Literal, NoReturn, Self

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
from .ddl import _changes_schema, _inline_ddl_params, classify_statement
from .errors import (
    PG_STALE_PLAN_EXCEPTIONS,
    _log_sql_error,
    is_handled_by_seam,
    mark_handled_by_seam,
    mark_stale_cached_plan,
    reached_the_server,
)
from .lifecycle import clear_prepared_cache
from .metrics import _MetricsMixin
from .pool import ConnectionPool
from .savepoint import Savepoint, _FlushingSavepoint
from .schema_cache import TransactionSchemaCache
from .utils import categorize_query

if TYPE_CHECKING:
    from odoo.orm.runtime import Transaction

_logger = logging.getLogger(__name__)

_TX_IDLE = _TxStatus.IDLE


def _statement_text(query: Any) -> str:
    """The text `classify_statement` reads, whatever the entry point was handed.

    One function because there were two, and they had drifted. `execute`
    decoded a `bytes` query; `executemany` spelled it `str(query)`, which for
    bytes yields a repr whose first two significant characters are `B` and a
    quote -- so `classify_statement` reports no DDL and no `ROLLBACK TO`,
    `_after_statement` skips `_invalidate_caches_after_ddl`, and
    `_schema_changed` stays False. That is exactly the asymmetry between the
    two entry points which `_after_statement` exists to close, reintroduced one
    level down, in the step that turns the argument into text.

    **This is defence, not a bug report.** `executemany`'s signature does not
    admit `bytes` and nothing in the tree passes it any; `execute`'s bytes
    handling exists because `test_db_cursor` pins it, and there is no
    equivalent caller for the other entry point. What makes the drift worth
    removing anyway is that a seam whose whole purpose is to keep two callers
    identical should not be fed by two different readers.
    """
    if isinstance(query, bytes):
        try:
            return query.decode()
        except UnicodeDecodeError:
            return ""
    return query if isinstance(query, str) else str(query)


def _rendered(query: Any) -> Any:
    """A statement entry point may hand the seam a thunk instead of a string.

    `copy_from` builds a `psycopg.sql.Composed` and rendering it is only ever
    needed on the error, DEBUG and hook paths; `TestCopyFromMetricsQueryLazy`
    pins that an ordinary COPY with no hook renders nothing at all.
    """
    return query() if callable(query) else query


class BaseCursor:
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
        self.commit_count = 0

    def flush(self) -> None:
        """Drive ORM writes and precommit hooks until neither produces more.

        **The pass limit bounds ONE shape of non-convergence, and the message
        it raises names that shape exactly.** A hook whose ORM writes make the
        next `transaction.flush()` produce more precommit work is caught: each
        round trip costs one pass and the eleventh raises.

        It cannot bound the other shape. `Callbacks.run` is
        `while self._funcs: popleft()(...)`, so a hook that calls
        `precommit.add` is drained inside the SAME `run()` -- measured, a hook
        re-arming itself ran 100 000 times in one call and never returned to
        this loop. That is deliberate where it matters (a hook enqueueing
        follow-up work should not wait a pass for it), and it means an
        unconditionally self-re-arming hook hangs the worker with no error
        rather than raising below. Bounding it belongs to `Callbacks`, which
        the whole framework shares, not here.
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
        if self.transaction is not None:
            self.transaction.clear()
        self.precommit.clear()

    def reset(self) -> None:
        if self.transaction is not None:
            self.transaction.reset()

    def discard_cached_plans(self) -> None:
        pass

    def _before_statement(self) -> None:
        pass

    def _on_rollback_to_savepoint(self) -> None:
        pass

    def execute(
        self,
        query: str | bytes | SQL | _sql.Composable,
        params: tuple | list | dict | None = None,
        log_exceptions: bool = True,
        prepare: bool | None = None,
    ) -> None:
        raise NotImplementedError

    def commit(self) -> None:
        raise NotImplementedError

    def rollback(self) -> None:
        raise NotImplementedError

    # These stay TYPE_CHECKING-only on purpose, and it is not the lie the
    # README retired when BaseCursor stopped inheriting psycopg.Cursor.
    # `odoo.tests.cursor.TestCursor` forwards them to the wrapped cursor
    # through `__getattr__`, which runs only for attributes the class does not
    # have; defining them here -- even as `raise NotImplementedError` -- would
    # shadow that forwarding and break every `cr.fetchone()` under a test
    # cursor. They declare the protocol subclasses must satisfy, not defaults.
    if TYPE_CHECKING:

        def close(self) -> None:
            pass

        def fetchone(self) -> tuple[Any, ...] | None:
            pass

        def fetchall(self) -> list[tuple[Any, ...]]:
            pass

        @property
        def closed(self) -> bool:
            pass

        @property
        def rowcount(self) -> int: ...

        @property
        def connection(self) -> psycopg.Connection: ...

    def savepoint(self, flush: bool = True) -> Savepoint:
        """Open a subtransaction. Never inside pipeline mode -- see below.

        A savepoint exists to make the next failure recoverable, and in
        pipeline mode it cannot: psycopg queues the commands and PostgreSQL
        discards everything after an error until the next sync, so the
        `ROLLBACK TO SAVEPOINT` the failure is supposed to trigger is one of
        the statements thrown away. Measured on a live cursor, the same
        UniqueViolation under the same savepoint:

            outside a pipeline   caught, `SELECT count(*)` answers -> (1,)
            inside a pipeline    caught, next statement raises
                                 InFailedSqlTransaction

        That is silent: the caller's `except UniqueViolation` runs exactly as
        written, and the transaction it thinks it repaired is dead. It takes
        out `insert_or_existing`, whose whole contract is that branch.

        **Refusing is not free, and the cost is measured rather than assumed.**
        `insert_or_existing` inside a pipeline WORKS today on the happy path
        -- verified: `ir.config_parameter.set_param` inside a `cr.pipeline()`
        returns normally when no conflict occurs, because the savepoint is
        opened and released without ever having to roll back. This turns that
        into a `RuntimeError`. It is still the right trade: the case that
        works is the one where the savepoint was never needed, and the case it
        exists for -- a concurrent insert -- is the one that corrupts the
        transaction. A helper whose error branch is broken is broken. Nothing
        in the tree composes the two (4870 tests across `/base`, `/test_orm`
        and `/test_new_api` pass with this in place), and failing at the
        composition point is far easier to read than `InFailedSqlTransaction`
        three frames later. `copy_from` refuses pipeline mode for its own
        reasons and sets the precedent for the shape.

        `getattr` rather than a `BaseCursor` attribute: `odoo.tests.cursor.
        TestCursor` forwards to the real cursor through `__getattr__`, which
        runs only for names the class does NOT have, so declaring a default
        here would answer False for a test cursor whose wrapped cursor is
        pipelining.
        """
        if getattr(self, "in_pipeline", False):
            raise RuntimeError(
                "cannot open a savepoint inside cr.pipeline(): PostgreSQL "
                "discards every queued statement after an error, so the "
                "ROLLBACK TO SAVEPOINT is discarded too and the transaction "
                "stays aborted. Take the savepoint around the pipeline block, "
                "not inside it."
            )
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
        row = self.fetchone()
        return row[0] if row else None

    def dictfetchone(self) -> dict[str, Any] | None:
        raise NotImplementedError

    def dictfetchmany(self, size: int) -> list[dict[str, Any]]:
        res: list[dict[str, Any]] = []
        while size > 0 and (row := self.dictfetchone()) is not None:
            res.append(row)
            size -= 1
        return res

    def dictfetchall(self) -> list[dict[str, Any]]:
        res: list[dict[str, Any]] = []
        while (row := self.dictfetchone()) is not None:
            res.append(row)
        return res

    def now(self) -> datetime:
        if self._now is None:
            self.execute("SELECT (now() AT TIME ZONE 'UTC')")
            row = self.fetchone()
            assert row is not None, "SELECT now() returned no row"
            self._now = row[0]
        return self._now


class Cursor(_BulkAccessMixin, _MetricsMixin, BaseCursor):
    _closed: bool = True

    __caller: tuple[str | None, int | str] | Literal[False]

    def __init__(
        self,
        pool: ConnectionPool,
        dbname: str,
        dsn: dict,
        key: frozenset | None = None,
    ):
        super().__init__()
        self._init_metrics_state()

        self._closed: bool = True

        self.__pool: ConnectionPool = pool
        self.dbname = dbname

        self._schema_cache = TransactionSchemaCache()
        self._schema_changed = False

        self._pipeline_depth = 0
        self._pipeline_stack: ExitStack | None = None
        self._pipeline_statements = 0
        self._pipeline_entered = False

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
        except BaseException:
            # BaseException, not Exception: everything between `pool.borrow`
            # above and `_closed = False` here runs while this cursor owns a
            # permit and a connection that no `close()` will ever reach --
            # `__del__` short-circuits on `_closed`, which is True for the
            # whole constructor. Measured with a KeyboardInterrupt injected at
            # `_cnx.cursor()`: `budget_in_use=1, checked_out=1` afterwards with
            # nothing left to release them, and `maxconn` of those leave every
            # later borrow timing out on "connection budget reached".
            #
            # NO REACHABLE TRIGGER IS KNOWN, and the obvious guesses were
            # checked and are wrong. `signal_time_expired_handler` raises
            # `CpuTimeLimitExceeded`, which subclasses `Exception` and the old
            # guard already caught; the work thread that opens cursors blocks
            # SIGXCPU/SIGINT/SIGQUIT/SIGUSR1/SIGUSR2 outright
            # (`service/_worker.py::_runloop`), so no Python signal handler
            # runs in this frame at all; and `limit_time_real` is a parent-side
            # SIGKILL, which no handler could intercept. This is kept on the
            # same terms `ConnectionPool.borrow`'s guard is kept on: it costs
            # nothing, the failure it prevents needs a restart to clear, and
            # "nothing raises here today" is not a property anyone can hold
            # still.
            obj = self.__dict__.get("_obj")
            if obj is not None:
                with suppress(Exception):
                    obj.close()
            # Same question `_close` asks: a connection whose setup raised
            # after a statement is sitting in a failed transaction, and
            # handing it back as warm is how the next borrower inherits it.
            pool.give_back(self._cnx, keep_in_pool=self._connection_is_clean())
            raise

    def dictfetchone(self) -> dict[str, Any] | None:
        row = self._obj.fetchone()
        if row is None:
            return None
        return {
            col.name: val for col, val in zip(self._obj.description, row, strict=True)
        }

    def _col_names(self) -> tuple[str, ...]:
        return tuple(col.name for col in self._obj.description)

    def _rows_to_dict_list(self, rows: list[tuple[Any, ...]]) -> list[dict[str, Any]]:
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
        return self._obj.nextset()

    @contextmanager
    def copy(
        self,
        statement: str | bytes | _sql.Composable,
        params: tuple | list | dict | None = None,
        *,
        writer: Any = None,
    ) -> Generator[Any]:
        """Open a COPY, timed and error-logged around the whole transfer.

        This used to `return self._obj.copy(...)` inside a `try/finally`.
        psycopg's `Cursor.copy` is a `@contextmanager`, so that call builds the
        manager and puts nothing on the wire: the timer closed before the COPY
        began and there was no `except` at all. Measured, 200 000 rows —
        **120.4 ms of transfer reported as 0.008 ms**, and a failing
        `cr.copy()` logged nothing where the same failure through `copy_from`
        logs `bad COPY:`. Wrapping the caller's `with` is what makes the
        timing describe the transfer.
        """
        self._before_statement()
        hooks = getattr(self._thread, "query_hooks", None)
        start = real_time() if hooks else 0.0
        t0 = monotonic()
        counts = False
        try:
            with self._obj.copy(statement, params, writer=writer) as copy:
                yield copy
            counts = True
        except Exception as e:
            counts = self._statement_failed(e, statement, label="COPY", prepared=False)
            raise
        finally:
            self._statement_done(
                monotonic() - t0,
                counts=counts,
                query=statement,
                params=params,
                label="COPY",
                hooks=hooks,
                start=start,
                debug=_logger.isEnabledFor(logging.DEBUG),
            )

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

    def _statement_failed(
        self,
        exc: Exception,
        query: Any,
        *,
        label: str = "query",
        log_exceptions: bool = True,
        prepared: bool = True,
    ) -> bool:
        """What a statement entry point owes a statement that raised.

        Returns whether it still counts. The timing, the hook fan-out, the
        DEBUG line, the error tier, the stale-plan mark and the counting
        decision were written out once per entry point -- four copies, each
        drifted differently, and every drift was a defect:

        - `executemany` never called `_note_stale_cached_plan`, so the replay
          `service.transaction.retrying` performs for `execute` did not happen
          for it. Measured on one connection across one `ALTER COLUMN … TYPE`:
          `execute` raised `FeatureNotSupported` marked and `executemany`
          raised the same error unmarked, and through `retrying()` the first
          recovered on its second call while the second propagated.
          `res_users` batches its writes with `executemany` on the request
          path.
        - `copy_from` recorded nothing when the COPY failed, against the rule
          that a statement which reached the server cost a round trip -- and
          `sql_log_count` is what `assertQueryCount` reads.
        - `cr.copy()` timed the construction of psycopg's `@contextmanager`
          rather than the transfer, and logged nothing on failure.

        A statement counts when it failed *at the server*: `reached_the_server`
        is the discriminator, because psycopg's own client-side rejections
        never reached the wire and counting them would inflate every query
        budget.

        Two plain methods rather than one `@contextmanager`, because the
        wrapper sits on the hot path. Measured against the inline envelope it
        replaces, with the wire stubbed out so the delta is pure Python,
        `Cursor.execute` cost **721.9 ns inline against 1888.5 ns behind a
        generator** -- +1167 ns per statement, in a function where 64 ns has
        been thought worth banking. The pair costs one call each and keeps
        every drift-prone decision in one place all the same.
        """
        if is_handled_by_seam(exc):
            # Reached twice for one error only when pipeline mode defers it
            # past the entry point that issued it; see `mark_handled_by_seam`.
            return reached_the_server(exc)
        mark_handled_by_seam(exc)
        if prepared:
            self._note_stale_cached_plan(exc)
        if log_exceptions:
            _log_sql_error(exc, _rendered(query), label=label)
        return reached_the_server(exc)

    def _statement_done(
        self,
        delay: float,
        *,
        counts: bool,
        query: Any,
        params: Any = None,
        count: int = 1,
        label: str = "query",
        hooks: Any = None,
        start: float = 0.0,
        debug: bool = False,
    ) -> None:
        """What it owes the statement once it is over, pass or fail.

        `debug` is passed in rather than asked for: the callers need the same
        answer again for their per-table stats, and `Logger.isEnabledFor` costs
        46 ns -- asking twice per statement was most of the 66 ns this seam
        cost over the inline envelope it replaced.
        """
        if debug:
            rows = f" ({count} rows)" if count != 1 else ""
            _logger.debug(
                "[%.3f ms] %s%s: %s",
                1000 * delay,
                label,
                rows,
                self._format(_rendered(query), params),
            )
        if counts:
            # only the hooks read `query`, and rendering a Composed COPY
            # statement is a real cost on a path that otherwise does none:
            # keep it None when nothing is listening.
            self._record_metrics(
                delay,
                count,
                query=_rendered(query) if hooks else None,
                params=params,
                start=start,
                hooks=hooks,
            )

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
            code, embedded = query.code, query.params
            query, params = code, embedded
        else:
            if isinstance(query, _sql.Composable):
                query = query.as_string(self._cnx)
            if params and not isinstance(params, (tuple, list, dict)):
                raise ValueError(
                    f"SQL query parameters should be a tuple, list or dict; got {params!r}"
                )

        query, params, prepare, qs, ddl_kw, rollback_to = self._resolve_ddl(
            query, params, prepare
        )

        if self._pipeline_stack is not None:
            self._arm_pipeline()

        debug = _logger.isEnabledFor(logging.DEBUG)
        hooks = getattr(self._thread, "query_hooks", None)
        start = real_time() if hooks else 0.0
        obj = self._obj
        t0 = monotonic()
        counts = False
        try:
            obj.execute(query, params, prepare=prepare)
            counts = True
        except Exception as e:
            counts = self._statement_failed(
                e, query, log_exceptions=log_exceptions, prepared=prepare is not False
            )
            raise
        finally:
            delay = monotonic() - t0
            self._statement_done(
                delay,
                counts=counts,
                query=query,
                params=params,
                hooks=hooks,
                start=start,
                debug=debug,
            )

        self._after_statement(qs, ddl_kw, rollback_to)

        if debug:
            query_type, table = categorize_query(qs)
            self._record_sql_log(query_type, table, delay)

    def _after_statement(self, qs: str, ddl_kw: str | None, rollback_to: bool) -> None:
        """What every statement owes the connection once it has succeeded.

        Shared with `executemany`, which classified nothing at all: a DDL run
        through it left `_schema_changed` False, so sibling connections were
        never drained and cached plans were never discarded. Nothing in the tree
        issues DDL that way today, but the same asymmetry between the two entry
        points was a real defect once before -- `_statement_failed`'s docstring
        records `executemany` skipping the stale-plan mark on the `res_users`
        write path -- and it was reintroduced one level up, in the seam that
        decides what a statement *was* rather than what to do when it failed.
        """
        if _changes_schema(qs, ddl_kw):
            self._invalidate_caches_after_ddl()
        elif rollback_to:
            self._on_rollback_to_savepoint()

    def _resolve_ddl(
        self,
        query: Any,
        params: tuple | list | dict | None,
        prepare: bool | None,
    ) -> tuple[Any, tuple | list | dict | None, bool | None, str, str | None, bool]:
        qs = _statement_text(query)
        ddl_kw, rollback_to = classify_statement(qs)
        if ddl_kw is not None:
            if params:
                query = _inline_ddl_params(qs, params, self._cnx)
                params = None
            if prepare is None:
                prepare = False
        return query, params, prepare, qs, ddl_kw, rollback_to

    def discard_cached_plans(self) -> None:
        if not clear_prepared_cache(self._cnx):
            _logger.warning(
                "psycopg no longer exposes Connection._prepared.clear(); "
                "auto-prepare is off for the rest of this cursor's life "
                "(restored when the connection returns to the pool). "
                "Re-check odoo.db.cursor against the installed psycopg.",
            )
            self._cnx.prepare_threshold = None
            self.execute("DEALLOCATE ALL")
        self._schema_cache.clear_catalog_facts()

    def _on_rollback_to_savepoint(self) -> None:
        self._schema_cache.clear()

    def _note_stale_cached_plan(self, exc: Exception) -> bool:
        if not isinstance(exc, PG_STALE_PLAN_EXCEPTIONS):
            return False
        prepared = getattr(self._cnx, "_prepared", None)
        if prepared is None or not getattr(prepared, "_names", None):
            return False
        clear_prepared_cache(self._cnx)
        self._schema_cache.clear_catalog_facts()
        mark_stale_cached_plan(exc)
        return True

    def _drain_sibling_connections(self) -> None:
        from . import drain_db

        drain_db(self.dbname)

    def _invalidate_caches_after_ddl(self) -> None:
        self.discard_cached_plans()
        self._schema_changed = True

    def executemany(
        self,
        query: str | SQL | _sql.Composable,
        params_seq: Iterable[tuple | list | dict],
        returning: bool = False,
        log_exceptions: bool = True,
    ) -> None:
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

        qs = _statement_text(query)
        ddl_kw, rollback_to = classify_statement(qs)

        rows: Collection[tuple | list | dict] = (
            params_seq if isinstance(params_seq, Collection) else list(params_seq)
        )
        if not rows:
            return

        if ddl_kw is not None and any(rows):
            # psycopg binds server-side and DDL takes no parameters, so this
            # reaches the server only to come back as `IndeterminateDatatype:
            # could not determine data type of parameter $1`, which names
            # neither the statement kind nor the entry point. `execute` inlines
            # DDL parameters instead (`_resolve_ddl`); there is no per-row
            # equivalent, because a DDL statement run once per row is not a
            # thing anyone means.
            raise ValueError(
                f"executemany() cannot run parameterised DDL ({ddl_kw}); "
                f"DDL takes no bound parameters. Issue it once with "
                f"cr.execute(), which inlines them."
            )

        if self._pipeline_stack is not None:
            self._arm_pipeline()

        debug = _logger.isEnabledFor(logging.DEBUG)
        hooks = getattr(self._thread, "query_hooks", None)
        start = real_time() if hooks else 0.0
        obj = self._obj
        t0 = monotonic()
        counts = False
        try:
            obj.executemany(query, rows, returning=returning)
            counts = True
        except Exception as e:
            counts = self._statement_failed(e, query, log_exceptions=log_exceptions)
            raise
        finally:
            delay = monotonic() - t0
            self._statement_done(
                delay,
                counts=counts,
                query=query,
                count=len(rows),
                hooks=hooks,
                start=start,
                debug=debug,
            )

        self._after_statement(qs, ddl_kw, rollback_to)

        if debug:
            query_type, table = categorize_query(qs)
            self._record_sql_log(query_type, table, delay)

    @property
    def in_pipeline(self) -> bool:
        return self._pipeline_entered

    def _arm_pipeline(self) -> None:
        self._pipeline_statements += 1
        if self._pipeline_statements == 2 and self._pipeline_stack is not None:
            self._pipeline_stack.enter_context(self._cnx.pipeline())
            self._pipeline_entered = True

    @contextmanager
    def pipeline(
        self, log_exceptions: bool = True, query: Any = None
    ) -> Generator[None]:
        """Batch this block's statements, and route the deferred error home.

        In pipeline mode psycopg does not raise where the statement was
        issued: it queues the command and surfaces the server's error at the
        next sync, which for this block is the `ExitStack` exit below --
        outside every entry point's own `try/except`, and therefore outside
        the failure seam that `_statement_failed` exists to be. Measured on
        one connection across one committed `ALTER COLUMN … TYPE`, with the
        SAME statement:

            plain cr.execute                raised FeatureNotSupported, marked
            cr.execute inside cr.pipeline() raised FeatureNotSupported, UNMARKED

        The mark is what `service.transaction.retrying` dispatches on, and
        end to end that is the whole difference: the same pipelined SELECT
        through `retrying()` raised `FeatureNotSupported` on its first attempt
        before this, and recovers on its second after.

        Which statements can reach it is narrower than "everything the ORM
        pipelines", and the first draft of this note got it wrong. PostgreSQL
        raises `cached plan must not change result type` only when the altered
        column is in the statement's RESULT descriptor: measured, a plain
        `UPDATE` and an `INSERT` without `RETURNING` are silently revalidated,
        and `UPDATE … RETURNING id` is too when `id` is not the altered
        column. So the 748 plain UPDATEs that `write.py::_update_rows_*_sql`
        contributes cannot reach it at all. What can, counted over `/base` +
        `/test_orm` + `/test_new_api`, is every result-returning statement the
        ORM runs inside an armed block: 44 SELECTs from
        `orm/runtime/environment.py::execute_query`, 25 and 9 from
        `addons/base/models/ir_default.py`, 26 `UPDATE … RETURNING` from the
        parent-store maintenance, and `create.py::_prepare_create_values`.

        The seam is idempotent (`is_handled_by_seam`),
        so a statement whose error DID surface at its own entry point -- an
        unarmed first statement, a client-side rejection -- passes through
        here untouched.

        `reached_the_server` gates it because this `except` also sees whatever
        the caller's block raised: a plain Python error carries no SQLSTATE
        and is none of the seam's business.

        `query` is what the error names. psycopg reports *that* a queued
        command failed and not *which*, so a block of unrelated statements can
        only say so; a block whose statements share one template --
        `execute_values` -- should pass it, or the log loses the SQL it used to
        carry.
        """
        if self._pipeline_depth:
            # Only the outermost block syncs, so only it can observe the
            # deferred error; a nested one would see nothing to route.
            self._pipeline_depth += 1
            try:
                yield
            finally:
                self._pipeline_depth -= 1
            return

        self._pipeline_depth = 1
        self._pipeline_statements = 0
        try:
            with ExitStack() as stack:
                self._pipeline_stack = stack
                yield
        except Exception as e:
            if reached_the_server(e):
                self._statement_failed(
                    e,
                    query
                    if query is not None
                    else "<pipelined statement; psycopg does not report which>",
                    label="pipelined statement",
                    log_exceptions=log_exceptions,
                )
            raise
        finally:
            self._pipeline_stack = None
            self._pipeline_depth = 0
            self._pipeline_entered = False

    def close(self) -> None:
        if not self._closed:
            self._close()

    def _close(self) -> None:
        keep_in_pool = True
        try:
            try:
                self.cache.clear()
                self.print_log()
            finally:
                try:
                    self._do_rollback()
                except Exception as exc:
                    keep_in_pool = self._connection_is_clean()
                    if keep_in_pool:
                        _logger.warning("Failed to roll back on cursor close")
                    elif not reached_the_server(exc):
                        # An outage, not a fault.  A rollback that never
                        # reached PostgreSQL carries no SQLSTATE, which is
                        # what `reached_the_server` reads -- the backend is
                        # gone and discarding the connection is the only
                        # thing left to do, so a traceback says nothing the
                        # message does not.  This is not a rare path: it is
                        # what BOTH cron loops hit every time PostgreSQL
                        # drops them, and each one has already reported it at
                        # WARNING ("Postgres connection lost, reconnecting").
                        # Measured on a live server whose cron/job backends
                        # were terminated: two ERROR tracebacks per outage,
                        # for an event the server handled correctly. Reporting
                        # handled operations as faults is what teaches an
                        # operator to skip ERROR.
                        _logger.warning(
                            "Discarding a connection whose backend is gone: %s",
                            exc,
                        )
                    else:
                        _logger.exception(
                            "Failed to roll back on cursor close; discarding connection"
                        )
            self._obj.close()
        finally:
            self._closed = True
            del self._obj
            self.__pool.give_back(self._cnx, keep_in_pool=keep_in_pool)

    def _connection_is_clean(self) -> bool:
        try:
            return self._cnx.info.transaction_status == _TX_IDLE
        except Exception:
            return False

    def commit(self) -> None:
        if self._closed:
            raise psycopg.InterfaceError("Cursor already closed")
        if self._savepoint_depth:
            raise RuntimeError(
                "Cannot commit inside a savepoint! "
                "This would corrupt the savepoint's rollback state."
            )
        self.flush()
        self._cnx.commit()
        self.commit_count += 1
        if self._schema_changed:
            self._schema_changed = False
            self._drain_sibling_connections()
        self.clear()
        self._schema_cache.clear()
        self._now = None
        self.prerollback.clear()
        self.postrollback.clear()
        self.postcommit.run()

    def rollback(self) -> None:
        if self._closed:
            raise psycopg.InterfaceError("Cursor already closed")
        if self._savepoint_depth:
            raise RuntimeError(
                "Cannot rollback inside a savepoint! "
                "Use cr.savepoint() for nested transaction control."
            )
        self._do_rollback()

    def _do_rollback(self) -> None:
        self.clear()
        self.postcommit.clear()
        try:
            self.prerollback.run()
        finally:
            self._cnx.rollback()
            self._schema_changed = False
            self._schema_cache.clear()
        self._now = None
        self.postrollback.run()

    def __getattr__(self, name: str) -> Any:
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
