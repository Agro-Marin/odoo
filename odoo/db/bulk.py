"""Bulk-data access for :class:`~odoo.db.cursor.Cursor`.

The COPY / multi-row VALUES machinery — ``copy_from`` (PostgreSQL COPY protocol,
optional binary mode and pre-generated ids), ``execute_values`` (single-``%s``
VALUES expansion) and the ``_get_column_types`` catalog lookup that binary COPY
needs — split out of :mod:`odoo.db.cursor` into a mixin so the core transaction
surface stays small.

``_BulkAccessMixin`` is **not** standalone: it is mixed into :class:`Cursor`
(``class Cursor(_BulkAccessMixin, BaseCursor)``) and relies on the cursor's own
``_obj`` / ``_cnx`` / ``dbname`` / ``execute`` / ``fetchone`` / ``fetchall`` /
``_record_metrics`` / ``_record_sql_log`` members, declared below for type
checkers under ``TYPE_CHECKING``.
"""

from __future__ import annotations

import logging
from contextlib import nullcontext as _nullcontext
from decimal import Decimal as _Decimal
from time import monotonic
from typing import TYPE_CHECKING, Any

from psycopg import sql as _sql

from odoo.tools import SQL
from odoo.tools.misc import real_time

from .ddl import _find_value_markers
from .errors import CURSOR_LOGGER_NAME, _log_sql_error
from .schema_cache import schema_cache

_logger = logging.getLogger(CURSOR_LOGGER_NAME)

if TYPE_CHECKING:
    import threading
    from typing import Protocol

    import psycopg

    class _CursorInternals(Protocol):
        """The host-cursor surface that :class:`_BulkAccessMixin` relies on.

        Single source of truth for the coupling between the bulk-access methods
        and their host :class:`~odoo.db.cursor.Cursor`.  Each mixin method
        annotates ``self`` with this Protocol (the canonical mypy mixin pattern),
        so the bodies type-check against exactly this surface without
        re-declaring Cursor's members on the mixin; ``Cursor`` is in turn
        asserted to satisfy it in ``cursor.py`` (also under ``TYPE_CHECKING``).
        Either side drifting from the other is then a static-analysis error
        rather than a latent ``AttributeError`` at runtime.

        Members are those provided by Cursor / BaseCursor, plus the one sibling
        mixin method (``_get_column_types``) that ``copy_from`` invokes through
        ``self``.
        """

        _obj: psycopg.Cursor
        _cnx: psycopg.Connection
        _thread: threading.Thread
        dbname: str

        def execute(
            self,
            query: str | SQL,
            params: tuple | list | dict | None = None,
            log_exceptions: bool = True,
        ) -> None: ...
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
        ) -> None: ...
        def _record_sql_log(
            self, query_type: str, table: str | None, delay: float
        ) -> None: ...
        def _get_column_types(
            self, table: str, columns: list[str]
        ) -> list[str]: ...
        def _resolve_id_sequence(self, table: str) -> str: ...


class _BulkAccessMixin:
    """COPY / VALUES bulk-data methods mixed into :class:`Cursor`.

    The methods annotate ``self`` with :class:`_CursorInternals` — a
    ``TYPE_CHECKING``-only Protocol — so their bodies type-check against the
    exact host-cursor surface they require, keeping that contract in one place
    instead of re-declaring Cursor's members on this mixin.
    """

    def execute_values(
        self: _CursorInternals,
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
        # The query must have exactly one real `%s` marker — the position
        # where the batched VALUES row-list gets expanded.  Any other `%s`
        # would produce malformed SQL with a parameter-count mismatch at
        # best.  Markers are located with an escape-aware scan: `%%`
        # sequences (literal percent, e.g. LIKE 'a%%s') are NOT markers.
        # Validate BEFORE the empty-argslist short-circuit (like page_size
        # above) so a malformed query is rejected regardless of batch size —
        # otherwise a caller's empty-data unit test passes a query that would
        # only blow up once real rows arrive in production.
        markers = _find_value_markers(query)
        if len(markers) != 1:
            raise ValueError(
                f"execute_values requires exactly one '%s' marker in the "
                f"query (for the VALUES list); got {len(markers)}."
            )
        marker_pos = markers[0]
        if not argslist:
            return [] if fetch else None
        results = []
        batches = range(0, len(argslist), page_size)
        # The text around the single marker is loop-invariant — split it once
        # rather than re-slicing ``query`` for every batch.
        prefix, suffix = query[:marker_pos], query[marker_pos + 2 :]
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
                full_query = f"{prefix}{', '.join(placeholders)}{suffix}"
                self.execute(full_query, params)
                if fetch:
                    results.extend(self.fetchall())
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
        if not columns:
            # An empty column list builds ``COPY t () FROM STDIN``, which
            # PostgreSQL rejects with a cryptic syntax error deep inside the
            # COPY context.  Fail fast at the boundary with an actionable
            # message, like the on_error / page_size validations.
            raise ValueError("copy_from: columns must be a non-empty list")
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
            # The count is needed up-front (to pre-generate that many ids) and
            # rows is iterated twice, so an unsized input must be materialized.
            # Only copy when it is actually unsized: the ORM bulk-create path
            # already passes a list, and copying it would waste a full O(rows)
            # allocation on the hottest import path.  Mirrors executemany()'s
            # sized-input handling.
            if not hasattr(rows, "__len__"):
                rows = list(rows)
            count = len(rows)
            if count == 0:
                return []
            seq_name = self._resolve_id_sequence(table)
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
            # ``(id_, *row)`` builds the id-prefixed tuple directly; a ``tuple(row)``
            # wrapper would be a redundant per-row copy (row is already a sequence).
            rows = [(id_, *row) for id_, row in zip(ids, rows, strict=True)]
        else:
            ids = None
            # Symmetric with the returning_ids ``count == 0`` short-circuit above:
            # a sized empty input would otherwise open and close a COPY for zero
            # rows — a wasted ~200us server round-trip.  Only sized inputs are
            # tested, so a one-shot generator is never consumed prematurely (an
            # empty generator falls through and the COPY loop is simply a no-op).
            if hasattr(rows, "__len__") and len(rows) == 0:
                return None

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

        # ``start`` (below) and ``metrics_query`` (after the COPY) are consumed
        # only by query_hooks (profiler).  Resolve hook presence once: skip both
        # the wall-clock read and the SQL render when none are installed — the
        # common case on this hot path (imports, module installs).
        have_hooks = getattr(self._thread, "query_hooks", None)
        start = real_time() if have_hooks else 0.0  # t0 (monotonic) for duration
        t0 = monotonic()
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
            # Route through _log_sql_error (not a bare _logger.error) so a
            # recoverable serialization failure / deadlock during a bulk COPY
            # is demoted to WARNING and retried, exactly like execute().  The
            # COPY statement is only rendered to text on this (rare) error path.
            # _log_sql_error lives in odoo.db.errors (not cursor) precisely so
            # this import can be top-level: cursor imports bulk's mixin at load,
            # so bulk cannot import from cursor at load.  It still logs under the
            # "odoo.db.cursor" logger that TestCopyFromRecoverableErrorLogLevel
            # asserts on.
            _log_sql_error(e, copy_stmt.as_string(self._obj), label="COPY")
            raise
        finally:
            delay = monotonic() - t0
            if _logger.isEnabledFor(logging.DEBUG):
                _logger.debug(
                    "[%.3f ms] COPY %s (%d rows)",
                    1000 * delay,
                    table,
                    row_count,
                )

        # Render copy_stmt to text only when a profiler query hook will read it
        # (``have_hooks``, resolved before the COPY).  Building the SQL string
        # unconditionally wasted a full render on every bulk insert in the common
        # no-hook case.  _record_metrics only forwards `query` to thread
        # query_hooks, so None is harmless when none are installed.
        metrics_query = copy_stmt.as_string(self._obj) if have_hooks else None
        self._record_metrics(delay, query=metrics_query, start=start)

        if _logger.isEnabledFor(logging.DEBUG):
            self._record_sql_log("into", table, delay)

        return ids

    def _resolve_id_sequence(self: _CursorInternals, table: str) -> str:
        """Return the sequence name backing *table*'s ``id`` column (cached).

        ``pg_get_serial_sequence`` only finds a sequence *owned* by the column,
        but ``_inherits`` child tables share the parent's sequence, so fall back
        to the ``pg_depend`` catalog, which finds the sequence referenced by the
        column's ``DEFAULT`` expression.

        The resolved name is memoized per ``(dbname, table)``.  ``set_id_sequence``
        itself skips session-local ``pg_temp.<seq>`` names: the cache key carries
        no session, so handing that name to another session whose same-named
        ``table`` is a *different* temp (or the permanent table the name shadows)
        would resolve ``pg_temp`` to the wrong — or a nonexistent — sequence.
        Permanent tables, the only ones that actually repeat across connections,
        still cache.

        :raises ValueError: if no serial sequence backs ``<table>.id``.
        """
        seq_name = schema_cache.get_id_sequence(self.dbname, table)
        if seq_name is not None:
            return seq_name
        self.execute(SQL("SELECT pg_get_serial_sequence(%s, 'id')", table))
        (seq_name,) = self.fetchone()
        if seq_name is None:
            # Shared sequence (e.g. _inherits): find via pg_depend.
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
        schema_cache.set_id_sequence(self.dbname, table, seq_name)
        return seq_name

    def _get_column_types(
        self: _CursorInternals, table: str, columns: list[str]
    ) -> list[str]:
        """Look up PostgreSQL base type names for binary COPY.

        Results are cached in the process-global ``schema_cache`` since schema
        doesn't change during a session.
        """
        types = schema_cache.get_column_types(self.dbname, table, columns)
        if types is None:
            self.execute(
                SQL(
                    # Resolve the table via ::regclass so search_path is honored
                    # (TEMP tables live in pg_temp_N, never current_schema).  This
                    # matches the pg_get_serial_sequence(table, 'id') resolution
                    # used for returning_ids — the two lookups must agree, or
                    # binary COPY into a temp table raises "column not found".
                    # n.nspname is fetched to detect temp relations (cache skip
                    # below); all rows share one attrelid, hence one namespace.
                    """SELECT a.attname, t.typname, n.nspname
                    FROM pg_attribute a
                    JOIN pg_type t ON a.atttypid = t.oid
                    JOIN pg_class c ON c.oid = a.attrelid
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE a.attrelid = %s::regclass
                      AND a.attnum > 0 AND NOT a.attisdropped
                      AND a.attname = ANY(%s)""",
                    table,
                    list(columns),
                )
            )
            rows = self.fetchall()
            type_map = {name: typ for name, typ, _ns in rows}
            missing = [col for col in columns if col not in type_map]
            if missing:
                raise ValueError(
                    f"copy_from: column(s) {missing} not found in table "
                    f"{table!r} (current_schema)"
                )
            types = [type_map[col] for col in columns]
            # Cache the resolved types.  set_column_types() itself skips temp
            # relations: the key is name-based, but a temp table lives in a
            # session-local pg_temp_* schema, so another session's same-named
            # temp (or the permanent table the name shadows) could be fed the
            # wrong types via binary COPY set_types().  (rows is non-empty — the
            # missing-column check passed, so rows[0][2] is this relation's
            # pg_namespace.nspname.)
            schema_cache.set_column_types(
                self.dbname, table, columns, types, namespace=rows[0][2]
            )
        return types
