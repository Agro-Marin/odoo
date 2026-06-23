"""In-memory storage backend for the ORM.

:class:`DictBackend` is an in-memory row store for pure-Python unit tests, used
in place of PostgreSQL when ``Transaction.storage`` is set.
"""

import typing
from collections import defaultdict
from operator import eq, ge, gt, le, lt, ne
from typing import Any

if typing.TYPE_CHECKING:
    from collections.abc import Callable

# Supported comparison operators for search_rows
_OPERATORS: dict[str, Callable] = {
    "=": eq,
    "!=": ne,
    "<": lt,
    "<=": le,
    ">": gt,
    ">=": ge,
    "in": lambda v, vals: v in vals,
    "not in": lambda v, vals: v not in vals,
}


class DictBackend:
    """In-memory storage backend for unit tests.

    Stores data as nested dicts ``{table: {id: {column: value}}}``, with
    per-table auto-incrementing IDs. Supports simple column-level searches
    (:meth:`search_rows`) for relational resolution (e.g. One2many reverse
    lookups), but NOT SQL queries, domains, or joins.

    The ORM dispatches against this storage-backend contract through the public
    row API only; ``_tables`` / ``_sequences`` are private, so the storage shape
    can change without breaking call sites.
    """

    __slots__ = ("_sequences", "_tables")

    def __init__(self) -> None:
        self._tables: dict[str, dict[int, dict[str, Any]]] = {}
        self._sequences: dict[str, int] = defaultdict(int)

    def fetch_rows(self, table: str, ids: list[int], columns: list[str]) -> list[tuple]:
        tbl = self._tables.get(table, {})
        result = []
        for id_ in ids:
            row = tbl.get(id_)
            if row is not None:
                result.append(tuple(row.get(col) for col in columns))
        return result

    def insert_rows(
        self, table: str, columns: list[str], rows: list[tuple]
    ) -> list[int]:
        tbl = self._tables.setdefault(table, {})
        new_ids: list[int] = []
        # strict=True so a column/row width mismatch fails loudly rather than
        # silently dropping columns.
        for row in rows:
            self._sequences[table] += 1
            id_ = self._sequences[table]
            tbl[id_] = dict(zip(columns, row, strict=True))
            new_ids.append(id_)
        return new_ids

    def put_rows(self, table: str, rows: "list[dict[str, Any]]") -> None:
        """Store pre-built row dicts, each of which must contain an ``id`` key.

        Overwrites any existing row with the same id and advances the table's id
        sequence past the highest id stored, so a later :meth:`next_id` cannot
        collide with an explicitly-assigned id.
        """
        tbl = self._tables.setdefault(table, {})
        seq = self._sequences[table]
        for row in rows:
            id_ = row["id"]
            tbl[id_] = row
            if id_ > seq:
                seq = id_
        self._sequences[table] = seq

    def update_rows(
        self, table: str, updates: list[tuple[int, dict[str, Any]]]
    ) -> None:
        tbl = self._tables.get(table)
        if tbl is None:
            return
        for id_, values in updates:
            row = tbl.get(id_)
            if row is not None:
                row.update(values)

    def upsert_rows(
        self, table: str, updates: "list[tuple[int, dict[str, Any]]]"
    ) -> None:
        """Update existing rows, or insert new ones keyed by the given id.

        Like :meth:`update_rows`, but a missing id inserts ``{"id": id,
        **values}`` rather than being skipped. Mirrors the ORM ``UPDATE ...
        FROM VALUES`` write path.
        """
        tbl = self._tables.setdefault(table, {})
        for id_, values in updates:
            row = tbl.get(id_)
            if row is not None:
                row.update(values)
            else:
                tbl[id_] = {"id": id_, **values}

    def delete_rows(self, table: str, ids: list[int]) -> None:
        tbl = self._tables.get(table)
        if tbl is None:
            return
        for id_ in ids:
            tbl.pop(id_, None)

    def get_row(self, table: str, id_: int) -> dict[str, Any] | None:
        """Return the full row dict for a single ID, or None."""
        return self._tables.get(table, {}).get(id_)

    def get_rows(
        self, table: str, ids: "list[int]"
    ) -> "dict[int, dict[str, Any]]":
        """Return ``{id: row_dict}`` for the given *ids* that exist.

        Batch form of :meth:`get_row` for the search/read paths.
        """
        tbl = self._tables.get(table, {})
        result: dict[int, dict[str, Any]] = {}
        for id_ in ids:
            row = tbl.get(id_)
            if row is not None:
                result[id_] = row
        return result

    def contains_ids(self, table: str, ids: "list[int]") -> "set[int]":
        """Return the subset of *ids* present in *table* (for ``exists``)."""
        tbl = self._tables.get(table, {})
        return {id_ for id_ in ids if id_ in tbl}

    def table_ids(self, table: str) -> list[int]:
        """Return all IDs in a table, in insertion order."""
        return list(self._tables.get(table, {}).keys())

    def row_count(self, table: str) -> int:
        """Return the number of rows in a table."""
        return len(self._tables.get(table, {}))

    def search_rows(
        self,
        table: str,
        column: str,
        value: Any,
        operator: str = "=",
    ) -> list[int]:
        """Return IDs where ``column <operator> value``.

        Used by InMemoryEnvironment for One2many resolution (find records whose
        Many2one points at a given target).

        >>> backend = DictBackend()
        >>> ids = backend.insert_rows("order", ["partner_id"], [(1,), (2,), (1,)])
        >>> backend.search_rows("order", "partner_id", 1)
        [1, 3]
        """
        op_fn = _OPERATORS.get(operator)
        if op_fn is None:
            raise ValueError(f"Unsupported operator: {operator!r}")
        tbl = self._tables.get(table, {})
        return [id_ for id_, row in tbl.items() if op_fn(row.get(column), value)]

    def next_id(self, table: str) -> int:
        """Return the next auto-incremented ID for *table* without inserting.

        Used by the ORM's ``_create()`` to generate record IDs before
        populating row data.
        """
        self._sequences[table] += 1
        return self._sequences[table]

    def __repr__(self) -> str:
        n_tables = len(self._tables)
        n_rows = sum(len(t) for t in self._tables.values())
        return f"<DictBackend tables={n_tables} rows={n_rows}>"
