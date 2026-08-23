import logging
import os
import threading
from collections.abc import Collection, Generator, Iterable
from contextlib import contextmanager, suppress
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
from .ddl import (
    _changes_schema,
    _ddl_keyword,
    _inline_ddl_params,
    _is_rollback_to_savepoint,
)
from .errors import (
    PG_STALE_PLAN_EXCEPTIONS,
    _log_sql_error,
    mark_stale_cached_plan,
    reached_the_server,
)
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

    if TYPE_CHECKING:

        def close(self) -> None:
            pass

        def fetchone(self) -> tuple[Any, ...] | None:
            pass

    def savepoint(self, flush: bool = True) -> Savepoint:
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

    def copy(
        self,
        statement: str | bytes | _sql.Composable,
        params: tuple | list | dict | None = None,
        *,
        writer: Any = None,
    ) -> Any:
        self._before_statement()
        hooks = getattr(self._thread, "query_hooks", None)
        start = real_time() if hooks else 0.0
        t0 = monotonic()
        try:
            return self._obj.copy(statement, params, writer=writer)
        finally:
            self._record_metrics(
                monotonic() - t0,
                query=statement,
                params=params,
                start=start,
                hooks=hooks,
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

        query, params, prepare, qs, ddl_kw = self._resolve_ddl(query, params, prepare)

        debug = _logger.isEnabledFor(logging.DEBUG)
        hooks = getattr(self._thread, "query_hooks", None)
        start = real_time() if hooks else 0.0
        obj = self._obj
        t0 = monotonic()
        failed = False
        try:
            obj.execute(query, params, prepare=prepare)
        except Exception as e:
            failed = reached_the_server(e)
            self._note_stale_cached_plan(e)
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
            if failed:
                self._record_metrics(
                    delay, query=query, params=params, start=start, hooks=hooks
                )

        if _changes_schema(qs, ddl_kw):
            self._invalidate_caches_after_ddl()
        elif ddl_kw is None and _is_rollback_to_savepoint(qs):
            self._on_rollback_to_savepoint()

        self._record_metrics(
            delay, query=query, params=params, start=start, hooks=hooks
        )

        if debug:
            query_type, table = categorize_query(qs)
            self._record_sql_log(query_type, table, delay)

    def _resolve_ddl(
        self,
        query: Any,
        params: tuple | list | dict | None,
        prepare: bool | None,
    ) -> tuple[Any, tuple | list | dict | None, bool | None, str, str | None]:
        """Decide what actually goes on the wire, and report the DDL verdict.

        PostgreSQL rejects `$N` in DDL structural positions, so a DDL statement
        has its parameters inlined as quoted literals here and is never
        auto-prepared. `qs` and the leading keyword travel back out because the
        caller needs them again afterwards, to decide whether the statement
        changed the schema.
        """
        if isinstance(query, bytes):
            try:
                qs = query.decode()
            except UnicodeDecodeError:
                qs = ""
        else:
            qs = query
        ddl_kw = _ddl_keyword(qs)
        if ddl_kw is not None:
            if params:
                query = _inline_ddl_params(qs, params, self._cnx)
                params = None
            if prepare is None:
                prepare = False
        return query, params, prepare, qs, ddl_kw

    def discard_cached_plans(self) -> None:
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
        self._schema_cache.clear()

    def _note_stale_cached_plan(self, exc: Exception) -> bool:
        if not isinstance(exc, PG_STALE_PLAN_EXCEPTIONS):
            return False
        prepared = getattr(self._cnx, "_prepared", None)
        if prepared is None or not getattr(prepared, "_names", None):
            return False
        with suppress(Exception):
            prepared.clear()
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

        rows: Collection[tuple | list | dict] = (
            params_seq if isinstance(params_seq, Collection) else list(params_seq)
        )
        if not rows:
            return

        hooks = getattr(self._thread, "query_hooks", None)
        start = real_time() if hooks else 0.0
        obj = self._obj
        t0 = monotonic()
        failed = False
        try:
            obj.executemany(query, rows, returning=returning)
        except Exception as e:
            failed = reached_the_server(e)
            if log_exceptions:
                _log_sql_error(e, query)
            raise
        finally:
            delay = monotonic() - t0
            if _logger.isEnabledFor(logging.DEBUG):
                _logger.debug(
                    "[%.3f ms] executemany (%d rows): %s",
                    1000 * delay,
                    len(rows),
                    query,
                )
            if failed:
                self._record_metrics(
                    delay, len(rows), query=query, start=start, hooks=hooks
                )

        self._record_metrics(delay, len(rows), query=query, start=start, hooks=hooks)

        if _logger.isEnabledFor(logging.DEBUG):
            query_type, table = categorize_query(query)
            self._record_sql_log(query_type, table, delay)

    @contextmanager
    def pipeline(self) -> Generator[None]:
        with self._cnx.pipeline():
            yield

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
                except Exception:
                    _logger.debug("Failed to roll back on cursor close", exc_info=True)
                    keep_in_pool = self._connection_is_clean()
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
