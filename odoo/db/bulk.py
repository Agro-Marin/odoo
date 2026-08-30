from __future__ import annotations

import logging
from contextlib import nullcontext as _nullcontext
from decimal import Decimal as _Decimal
from time import monotonic
from typing import TYPE_CHECKING, Any

from psycopg import errors as _errors
from psycopg import pq as _pq
from psycopg import sql as _sql
from psycopg.adapt import Transformer as _Transformer
from psycopg.types.json import Jsonb as _Jsonb

from odoo.tools import SQL
from odoo.tools.misc import real_time

from .errors import CURSOR_LOGGER_NAME, reached_the_server
from .utils import find_value_markers

_logger = logging.getLogger(CURSOR_LOGGER_NAME)

_TEXT_OID = 25
_NUMERIC_OID = 1700
_JSON_OIDS: frozenset[int] = frozenset({114, 3802})


def _raw_json(value: str) -> str:
    return value


_BINARY_NUMERIC_MAX_FRACTION = 0.25


def _table_identifier(table: str) -> _sql.Identifier:
    return _sql.Identifier(*table.split("."))


if TYPE_CHECKING:
    import threading
    from collections.abc import Iterable, Iterator
    from contextlib import AbstractContextManager
    from typing import Protocol

    import psycopg

    from .schema_cache import TransactionSchemaCache

    class _CursorInternals(Protocol):
        _obj: psycopg.Cursor
        _cnx: psycopg.Connection
        _thread: threading.Thread
        _schema_cache: TransactionSchemaCache
        dbname: str

        def execute(
            self,
            query: str | SQL | _sql.Composable,
            params: tuple | list | dict | None = None,
            log_exceptions: bool = True,
        ) -> None: ...

        in_pipeline: bool

        def pipeline(
            self, log_exceptions: bool = True, query: Any = None
        ) -> AbstractContextManager[None]: ...
        def fetchone(self) -> tuple[Any, ...] | None: ...
        def fetchall(self) -> list[tuple[Any, ...]]: ...
        def _record_metrics(
            self,
            delay: float,
            count: int = 1,
            *,
            query: Any = None,
            params: Any = None,
            start: float = 0.0,
            hooks: Any = None,
        ) -> None: ...
        def _record_sql_log(
            self, query_type: str, table: str | None, delay: float
        ) -> None: ...
        def _before_statement(self) -> None: ...
        def _statement_failed(
            self,
            exc: Exception,
            query: Any,
            *,
            label: str = "query",
            log_exceptions: bool = True,
            prepared: bool = True,
        ) -> bool: ...
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
        ) -> None: ...
        def _get_column_type_oids(
            self, table: str, columns: list[str]
        ) -> list[int]: ...
        def _can_dump_binary(self, oids: list[int]) -> bool: ...
        def _binary_pays_off(self, oids: list[int]) -> bool: ...
        def _resolve_id_sequence(self, table: str) -> str: ...
        def _lock_table_for_bulk(self, table: str) -> None: ...
        def _preallocate_copy_ids(self, table: str, count: int) -> list[int]: ...


def _validate_copy_args(
    cursor: _CursorInternals,
    table: str,
    columns: list[str],
    returning_ids: bool,
    binary: bool,
    on_error: str | None,
) -> None:
    if not columns:
        raise ValueError("copy_from: columns must be a non-empty list")
    if on_error is not None and on_error not in ("ignore", "stop"):
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
    if cursor.in_pipeline:
        raise _errors.NotSupportedError(
            f"copy_from({table!r}) cannot run inside pipeline mode; "
            f"use execute_values, or move the COPY out of the enclosing "
            f"cr.pipeline() block."
        )


def _copy_statement(
    table: str, columns: list[str], binary: bool, on_error: str | None
) -> _sql.Composed:
    copy_opts = []
    if binary:
        copy_opts.append("FORMAT BINARY")
    if on_error and not binary:
        copy_opts.append(f"ON_ERROR {on_error}")
    if copy_opts:
        opts_sql = _sql.SQL(" ({})".format(", ".join(copy_opts)))
    else:
        opts_sql = _sql.SQL("")
    return _sql.SQL("COPY {} ({}) FROM STDIN{}").format(
        _table_identifier(table),
        _sql.SQL(", ").join(map(_sql.Identifier, columns)),
        opts_sql,
    )


def _note_binary_needs_exact_types(exc: Exception, table: str, columns: list) -> None:
    if reached_the_server(exc):
        return
    exc.add_note(
        f"copy_from({table!r}, binary=True) encodes values client-side from "
        f"the column types, which needs exactly the Python type each column "
        f"takes (int for int4, datetime.date for date, uuid.UUID for uuid). "
        f"Text COPY accepts a string for any of them; binary does not. "
        f"Columns: {columns}."
    )


def _coerced_rows(rows: Iterable[Any], col_types: list[int]) -> Iterator[Any]:
    numeric_idxs = tuple(i for i, oid in enumerate(col_types) if oid == _NUMERIC_OID)
    json_idxs = tuple(i for i, oid in enumerate(col_types) if oid in _JSON_OIDS)
    if not (numeric_idxs or json_idxs):
        yield from rows
        return
    for row in rows:
        row = list(row)
        for i in numeric_idxs:
            if isinstance(row[i], float):
                row[i] = _Decimal(str(row[i]))
        for i in json_idxs:
            if isinstance(row[i], str):
                row[i] = _Jsonb(row[i], dumps=_raw_json)
        yield row


class _BulkAccessMixin:
    def execute_values(
        self: _CursorInternals,
        query: str | _sql.Composable,
        argslist: list[Any],
        template: str | None = None,
        page_size: int = 100,
        fetch: bool = False,
        log_exceptions: bool = True,
    ) -> list[tuple[Any, ...]] | None:
        if isinstance(query, _sql.Composable):
            query = query.as_string(self._obj)
        if page_size <= 0:
            raise ValueError(f"execute_values page_size must be >= 1, got {page_size}")
        markers = find_value_markers(query)
        if len(markers) != 1:
            raise ValueError(
                f"execute_values requires exactly one '%s' marker in the "
                f"query (for the VALUES list); got {len(markers)}."
            )
        marker_pos = markers[0]
        if not argslist:
            return [] if fetch else None
        self._before_statement()
        results = []
        batches = range(0, len(argslist), page_size)
        prefix, suffix = query[:marker_pos], query[marker_pos + 2 :]
        use_pipeline = len(argslist) > page_size and not fetch
        ctx = (
            self.pipeline(log_exceptions=log_exceptions, query=query)
            if use_pipeline
            else _nullcontext()
        )
        ph_by_len: dict[int, str] = {}
        try:
            with ctx:
                for i in batches:
                    batch = argslist[i : i + page_size]
                    placeholders = []
                    params: list[Any] = []
                    for row in batch:
                        if isinstance(row, (list, tuple)):
                            if template:
                                placeholders.append(template)
                            elif (ph := ph_by_len.get(len(row))) is not None:
                                placeholders.append(ph)
                            else:
                                ph = "(" + ", ".join(["%s"] * len(row)) + ")"
                                ph_by_len[len(row)] = ph
                                placeholders.append(ph)
                            params.extend(row)
                        else:
                            placeholders.append(template or "(%s)")
                            params.append(row)
                    full_query = f"{prefix}{', '.join(placeholders)}{suffix}"
                    self.execute(full_query, params, log_exceptions)
                    if fetch:
                        results.extend(self.fetchall())
        except Exception as e:
            if reached_the_server(e):
                self._statement_failed(e, query, log_exceptions=log_exceptions)
            raise
        return results if fetch else None

    def copy_from(
        self: _CursorInternals,
        table: str,
        columns: list[str],
        rows,
        *,
        returning_ids: bool = False,
        binary: bool = False,
        on_error: str | None = None,
        log_exceptions: bool = True,
    ) -> list[int] | None:
        _validate_copy_args(self, table, columns, returning_ids, binary, on_error)
        self._before_statement()

        if returning_ids:
            if not hasattr(rows, "__len__"):
                rows = list(rows)
            count = len(rows)
            if count == 0:
                return []
            ids = self._preallocate_copy_ids(table, count)
            columns = ["id", *columns]
            rows = [(id_, *row) for id_, row in zip(ids, rows, strict=True)]
        else:
            ids = None
            if hasattr(rows, "__len__") and len(rows) == 0:
                return None

        col_types = self._get_column_type_oids(table, columns) if binary else None
        if col_types is not None and not self._binary_pays_off(col_types):
            binary = False
            col_types = None

        copy_stmt = _copy_statement(table, columns, binary, on_error)
        write_rows = _coerced_rows(rows, col_types) if col_types else rows

        def rendered() -> str:
            return copy_stmt.as_string(obj)

        hooks = getattr(self._thread, "query_hooks", None)
        start = real_time() if hooks else 0.0
        obj = self._obj
        debug = _logger.isEnabledFor(logging.DEBUG)
        t0 = monotonic()
        counts = False
        try:
            with obj.copy(copy_stmt) as copy:
                if col_types:
                    copy.set_types(col_types)
                for row in write_rows:
                    copy.write_row(row)
            counts = True
        except Exception as e:
            if binary:
                _note_binary_needs_exact_types(e, table, columns)
            counts = self._statement_failed(
                e, rendered, label="COPY", log_exceptions=log_exceptions, prepared=False
            )
            raise
        finally:
            delay = monotonic() - t0
            self._statement_done(
                delay,
                counts=counts,
                query=rendered,
                label="COPY",
                hooks=hooks,
                start=start,
                debug=debug,
            )

        if debug:
            self._record_sql_log("into", table, delay)

        return ids

    def _preallocate_copy_ids(
        self: _CursorInternals, table: str, count: int
    ) -> list[int]:
        self.execute(
            SQL(
                "SELECT nextval(%s::regclass) FROM generate_series(1, %s)",
                self._resolve_id_sequence(table),
                count,
            )
        )
        return [row[0] for row in self.fetchall()]

    def _lock_table_for_bulk(self: _CursorInternals, table: str) -> None:
        cache = self._schema_cache
        if table in cache.locked_tables:
            return
        self.execute(
            _sql.SQL("LOCK TABLE {} IN ROW EXCLUSIVE MODE").format(
                _table_identifier(table)
            )
        )
        cache.locked_tables.add(table)

    def _resolve_id_sequence(self: _CursorInternals, table: str) -> str:
        cache = self._schema_cache
        seq_name = cache.get_id_sequence(table)
        if seq_name is not None:
            return seq_name
        ident = _table_identifier(table).as_string(self._cnx)
        self.execute(SQL("SELECT pg_get_serial_sequence(%s, 'id')", ident))
        row = self.fetchone()
        assert row is not None, "pg_get_serial_sequence returned no row"
        (seq_name,) = row
        if seq_name is None:
            self.execute(
                SQL(
                    """SELECT s.oid::regclass::text
                FROM pg_attrdef ad
                JOIN pg_attribute a ON a.attrelid = ad.adrelid
                    AND a.attnum = ad.adnum
                JOIN pg_depend d ON d.objid = ad.oid
                    AND d.classid = 'pg_attrdef'::regclass
                    AND d.refclassid = 'pg_class'::regclass
                JOIN pg_class s ON s.oid = d.refobjid
                    AND s.relkind = 'S'
                WHERE ad.adrelid = %s::regclass AND a.attname = 'id'
                LIMIT 1""",
                    ident,
                )
            )
            row = self.fetchone()
            if not row or not row[0]:
                raise ValueError(f"No serial sequence found for {table}.id")
            seq_name = row[0]
        cache.set_id_sequence(table, seq_name)
        return seq_name

    def _binary_pays_off(self: _CursorInternals, oids: list[int]) -> bool:
        if not self._can_dump_binary(oids):
            return False
        numeric = sum(1 for oid in oids if oid == _NUMERIC_OID)
        return numeric <= len(oids) * _BINARY_NUMERIC_MAX_FRACTION

    def _can_dump_binary(self: _CursorInternals, oids: list[int]) -> bool:
        try:
            _Transformer(self._cnx).set_dumper_types(oids, _pq.Format.BINARY)
        except _errors.Error:
            _logger.debug(
                "copy_from: no binary dumper for type oid(s) %s; using text COPY",
                oids,
            )
            return False
        return True

    def _get_column_type_oids(
        self: _CursorInternals, table: str, columns: list[str]
    ) -> list[int]:
        cache = self._schema_cache
        types = cache.get_column_types(table, columns)
        if types is None:
            self._lock_table_for_bulk(table)
            self.execute(
                SQL(
                    """WITH RECURSIVE resolved AS (
                        SELECT a.attname::text AS name, a.atttypid AS type_oid,
                               t.typtype, t.typbasetype, 0 AS depth
                          FROM pg_attribute a
                          JOIN pg_type t ON t.oid = a.atttypid
                         WHERE a.attrelid = %s::regclass
                           AND a.attnum > 0 AND NOT a.attisdropped
                           AND a.attname = ANY(%s)
                        UNION ALL
                        SELECT r.name, b.oid, b.typtype, b.typbasetype, r.depth + 1
                          FROM resolved r
                          JOIN pg_type b ON b.oid = r.typbasetype
                         WHERE r.typtype = 'd' AND r.depth < 16
                    )
                    SELECT DISTINCT ON (name)
                           name,
                           CASE WHEN typtype = 'e' THEN %s::oid ELSE type_oid END
                      FROM resolved
                     ORDER BY name, depth DESC""",
                    _table_identifier(table).as_string(self._cnx),
                    list(columns),
                    _TEXT_OID,
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
            cache.set_column_types(table, columns, types)
        return types
