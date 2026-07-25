"""Bulk-data access for :class:`~odoo.db.cursor.Cursor`.

The COPY / multi-row VALUES machinery — ``copy_from`` (PostgreSQL COPY protocol,
optional binary mode and pre-generated ids), ``execute_values`` (single-``%s``
VALUES expansion) and the ``_get_column_type_oids`` catalog lookup that binary
COPY needs — split out of :mod:`odoo.db.cursor` into a mixin so the core transaction
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

from psycopg import errors as _errors
from psycopg import pq as _pq
from psycopg import sql as _sql
from psycopg.adapt import Transformer as _Transformer

from odoo.tools import SQL
from odoo.tools.misc import real_time

from .ddl import _find_value_markers
from .errors import CURSOR_LOGGER_NAME, _log_sql_error

_logger = logging.getLogger(CURSOR_LOGGER_NAME)

_TEXT_OID = 25
_NUMERIC_OID = 1700

if TYPE_CHECKING:
    import threading
    from typing import Protocol

    import psycopg

    from .schema_cache import TransactionSchemaCache

    class _CursorInternals(Protocol):
        """The host-cursor surface that :class:`_BulkAccessMixin` relies on.

        Each mixin method annotates ``self`` with this Protocol so its body
        type-checks against exactly these members without re-declaring Cursor's;
        ``Cursor`` is asserted to satisfy it in ``cursor.py``, so either side
        drifting is a type error, not a latent runtime ``AttributeError``.
        """

        _obj: psycopg.Cursor
        _cnx: psycopg.Connection
        _thread: threading.Thread
        _schema_cache: TransactionSchemaCache
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
            hooks: Any = None,
        ) -> None: ...
        def _record_sql_log(
            self, query_type: str, table: str | None, delay: float
        ) -> None: ...
        def _get_column_type_oids(
            self, table: str, columns: list[str]
        ) -> list[int]: ...
        def _can_dump_binary(self, oids: list[int]) -> bool: ...
        def _resolve_id_sequence(self, table: str) -> str: ...
        def _lock_table_for_bulk(self, table: str) -> None: ...


class _BulkAccessMixin:
    """COPY / VALUES bulk-data methods mixed into :class:`Cursor`.

    The methods annotate ``self`` with :class:`_CursorInternals` so their bodies
    type-check against the exact host-cursor surface they require.
    """

    def execute_values(
        self: _CursorInternals,
        query: str | _sql.Composable,
        argslist: list[Any],
        template: str | None = None,
        page_size: int = 100,
        fetch: bool = False,
        log_exceptions: bool = True,
    ) -> list[tuple[Any, ...]] | None:
        """Execute a query with multiple parameter sets using VALUES clause.

        Builds a single query with multiple VALUES rows per batch, useful for
        patterns like ``UPDATE ... FROM (VALUES %s) AS source(...)``.

        For simple multi-row INSERTs, prefer :meth:`executemany` which
        auto-pipelines for better performance.

        :param query: SQL containing exactly one ``%s`` marker for the VALUES list
        :param argslist: one sequence (or scalar) of parameters per VALUES row
        :param template: placeholder snippet for one row, e.g. ``(%s, %s::int)``;
            defaults to one built from each row's length
        :param page_size: rows per batched statement
        :param fetch: return every result row instead of ``None``; also disables
            the pipelining used for multi-batch runs
        :param log_exceptions: If False, suppress logging of failures (the
            caller logs its own message).  Symmetric with :meth:`Cursor.execute`
            and :meth:`Cursor.executemany` — without it a caller could quiet a
            single-statement failure but not its batched equivalent, which is
            exactly the case where the log is noisiest.
        """
        if isinstance(query, _sql.Composable):
            query = query.as_string(self._obj)
        if page_size <= 0:
            raise ValueError(f"execute_values page_size must be >= 1, got {page_size}")
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
        prefix, suffix = query[:marker_pos], query[marker_pos + 2 :]
        use_pipeline = len(argslist) > page_size and not fetch
        ctx = self._cnx.pipeline() if use_pipeline else _nullcontext()
        ph_by_len: dict[int, str] = {}
        try:
            with ctx:
                for i in batches:
                    batch = argslist[i : i + page_size]
                    placeholders = []
                    params = []
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
            if use_pipeline and log_exceptions:
                _log_sql_error(e, query)
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
        :param binary: If True, *prefer* binary COPY format (faster, but
            requires exact type matching via ``set_types()``).  Column type
            OIDs are looked up from ``pg_attribute`` and cached per
            transaction.  This is a performance hint, not a guarantee: a table
            with a column psycopg cannot encode client-side (an extension type
            such as PostGIS ``geometry`` or ``vector``, a composite, a range)
            silently falls back to text COPY, which inserts identical rows —
            see :meth:`_can_dump_binary`.
        :param on_error: Error handling for data type conversion errors
            (PG17+, text/CSV mode only).  ``'ignore'`` skips malformed rows
            instead of aborting the entire operation.  Useful for fault-
            tolerant data imports.  Rejected with ``binary=True`` (the
            option has no effect in binary mode) or ``returning_ids=True``
            (the pre-allocated sequence IDs cannot be reconciled with
            server-side row skipping — use batched INSERT … RETURNING).
        :param log_exceptions: If False, suppress logging of failures (the
            caller logs its own message).  Symmetric with
            :meth:`Cursor.execute` / :meth:`Cursor.executemany`.
        :return: list of generated IDs when *returning_ids* is True, else None

        .. note::
            **Query accounting.**  A COPY of N rows counts as **one** query
            (``sql_counter``, the thread's ``query_count``,
            ``assertQueryCount``), because it is one statement in one
            round-trip.  :meth:`Cursor.executemany` of N rows counts **N** —
            also one round-trip, but N statements for the server to plan and
            execute.  The asymmetry is deliberate: the counters exist to expose
            how much SQL work was asked for (the N+1 patterns
            ``assertQueryCount`` hunts), not how many packets were sent.
        """
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
        if returning_ids:
            if not hasattr(rows, "__len__"):
                rows = list(rows)
            count = len(rows)
            if count == 0:
                return []
            seq_name = self._resolve_id_sequence(table)
            self.execute(
                SQL(
                    "SELECT nextval(%s::regclass) FROM generate_series(1, %s)",
                    seq_name,
                    count,
                )
            )
            ids = [row[0] for row in self.fetchall()]
            columns = ["id", *columns]
            rows = [(id_, *row) for id_, row in zip(ids, rows, strict=True)]
        else:
            ids = None
            if hasattr(rows, "__len__") and len(rows) == 0:
                return None

        col_types = self._get_column_type_oids(table, columns) if binary else None
        if col_types is not None and not self._can_dump_binary(col_types):
            binary = False
            col_types = None

        cols_sql = _sql.SQL(", ").join(map(_sql.Identifier, columns))
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

        if col_types:
            _numeric_idxs = frozenset(
                i for i, oid in enumerate(col_types) if oid == _NUMERIC_OID
            )
        else:
            _numeric_idxs = None

        have_hooks = getattr(self._thread, "query_hooks", None)
        start = real_time() if have_hooks else 0.0
        obj = self._obj
        t0 = monotonic()
        row_count = 0
        try:
            with obj.copy(copy_stmt) as copy:
                if col_types:
                    copy.set_types(col_types)
                for row in rows:
                    if _numeric_idxs:
                        row = list(row)
                        for i in _numeric_idxs:
                            v = row[i]
                            if isinstance(v, float):
                                row[i] = _Decimal(str(v))
                    copy.write_row(row)
                    row_count += 1
        except Exception as e:
            if log_exceptions:
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

        metrics_query = copy_stmt.as_string(self._obj) if have_hooks else None
        self._record_metrics(delay, query=metrics_query, start=start, hooks=have_hooks)

        if _logger.isEnabledFor(logging.DEBUG):
            self._record_sql_log("into", table, delay)

        return ids

    def _lock_table_for_bulk(self: _CursorInternals, table: str) -> None:
        """Take COPY's own ``ROW EXCLUSIVE`` lock *before* reading column types.

        Binary COPY encodes every value **client-side** from types read out of
        the catalog, so those types are only authoritative while a lock
        conflicting with ``ACCESS EXCLUSIVE`` is held.  Without this, a
        concurrent ``ALTER TABLE`` can commit while our ``COPY`` sits waiting
        for its lock, and the COPY then writes values encoded with the *pre*-DDL
        types — silently, for a same-width change such as ``int4`` → ``date``.
        The window is as long as the DDL transaction runs, so it is not a narrow
        race.

        Deliberately NOT taken for :meth:`_resolve_id_sequence`: a stale
        sequence name cannot corrupt anything, it can only fail loudly
        (``nextval`` on a dropped sequence raises ``UndefinedTable``; ids from a
        swapped sequence collide on the primary key).  Paying a lock round-trip
        there would cost every text-mode ``returning_ids`` COPY a query for no
        correctness gain.

        This is the same lock mode on the same relation that ``COPY`` acquires
        anyway, just taken a few hundred microseconds earlier and (as always)
        held to end of transaction: no new lock ordering, no new deadlock class,
        no new blocking behaviour.  Issued once per table per transaction.
        """
        cache = self._schema_cache
        if table in cache.locked_tables:
            return
        self.execute(SQL("LOCK TABLE %s IN ROW EXCLUSIVE MODE", SQL.identifier(table)))
        cache.locked_tables.add(table)

    def _resolve_id_sequence(self: _CursorInternals, table: str) -> str:
        """Return the sequence name backing *table*'s ``id`` column.

        ``pg_get_serial_sequence`` only finds a sequence *owned* by the column,
        but ``_inherits`` children share the parent's, so fall back to
        ``pg_depend`` (the sequence referenced by the column's ``DEFAULT``).
        Memoized on the cursor for this transaction only (see
        :mod:`odoo.db.schema_cache`).

        No table lock is taken here — unlike the column types this value is
        never used to encode data client-side, so a stale name fails loudly
        rather than corrupting (see :meth:`_lock_table_for_bulk`).

        :raises ValueError: if no serial sequence backs ``<table>.id``.
        """
        cache = self._schema_cache
        seq_name = cache.get_id_sequence(table)
        if seq_name is not None:
            return seq_name
        self.execute(SQL("SELECT pg_get_serial_sequence(%s, 'id')", table))
        (seq_name,) = self.fetchone()
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
                    table,
                )
            )
            row = self.fetchone()
            if not row or not row[0]:
                raise ValueError(f"No serial sequence found for {table}.id")
            seq_name = row[0]
        cache.set_id_sequence(table, seq_name)
        return seq_name

    def _can_dump_binary(self: _CursorInternals, oids: list[int]) -> bool:
        """True when psycopg can encode every one of *oids* in binary format.

        Binary COPY makes the *client* produce the on-the-wire bytes, so it only
        works for types psycopg has a binary dumper for.  Anything outside that
        set — an extension type (``vector`` from the ``ai`` chain, PostGIS
        ``geometry``), a composite, a range — has a server-assigned OID psycopg
        has never heard of, and ``set_types()`` raises *inside* the COPY context.

        Asking up front turns that crash into a one-line decision to use text
        COPY instead, which encodes the same rows through the same adapters and
        differs only in speed.  ``binary=True`` is therefore a performance hint,
        not a semantic request: a caller that needs to know can compare the
        returned row count / ids, but nothing about the inserted data changes.

        The probe runs ``Transformer.set_dumper_types`` — the *exact* call
        :meth:`psycopg.Copy.set_types` makes — rather than looking the dumper
        classes up in ``connection.adapters``.  The two disagree: a lookup finds
        a generic array dumper for *any* array OID, but instantiating it also
        resolves the ELEMENT dumper, and that is what fails for ``point[]``,
        ``xml[]``, ``bpchar[]``, ``money[]`` and 36 other array types.  A
        class-only lookup therefore passed them and let the crash back into the
        COPY context — the very failure this guard exists to remove.  Sharing
        psycopg's own code path leaves no fidelity gap to drift (asserted over
        every column-capable type in ``pg_type`` by
        ``TestCanDumpBinaryMatchesSetTypes``).
        """
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
        """Look up the PostgreSQL type OID to encode each column as, for binary COPY.

        OIDs rather than ``pg_type.typname``: psycopg resolves a *name* through
        its type registry, which only knows the built-in scalar names — so an
        array column (``typname`` ``_int4``) raised ``KeyError: couldn't find the
        type '_int4'`` even though psycopg dumps ``int4[]`` perfectly well by
        OID.  An OID is also unambiguous, where a bare ``typname`` is not
        (two schemas may hold same-named types).

        The recursive CTE below costs about 20 µs more than the plain
        ``pg_type`` join it replaced (measured: 75 µs -> 95 µs over
        ``res_partner``'s 41 columns).  That is paid once per (table, columns)
        per transaction, against a COPY that exists to move thousands of rows,
        so uniform correctness is the right trade — but it *is* a cost, not a
        saving.

        Two type classes need translating rather than passing through:

        * **domains** resolve to their ultimate base type (recursively — a
          domain over a domain is legal).  PostgreSQL assigns each domain a
          fresh OID no dumper is registered for, but a domain's wire format *is*
          its base type's.
        * **enums** resolve to ``text``: ``enum_recv`` reads the label as a
          plain string, so the binary representation is byte-identical, and the
          per-enum OID would again have no dumper.

        Anything still undumpable (extension types, composites, ranges) is
        caught by :meth:`_can_dump_binary`, which falls back to text COPY.

        Read under the ``ROW EXCLUSIVE`` lock taken by
        :meth:`_lock_table_for_bulk` and memoized on the cursor for the rest of
        this transaction — binary COPY encodes values client-side, so feeding
        ``set_types()`` a type the table no longer has corrupts the COPY.  See
        :mod:`odoo.db.schema_cache` for why this must not outlive the lock.
        """
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
                    table,
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
