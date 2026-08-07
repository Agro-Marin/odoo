import typing
from collections import defaultdict
from operator import eq, ge, gt, le, lt, ne
from typing import Any

if typing.TYPE_CHECKING:
    from collections.abc import Callable

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
        for row in rows:
            self._sequences[table] += 1
            id_ = self._sequences[table]
            tbl[id_] = dict(zip(columns, row, strict=True))
            new_ids.append(id_)
        return new_ids

    def put_rows(self, table: str, rows: list[dict[str, Any]]) -> None:
        tbl = self._tables.setdefault(table, {})
        seq = self._sequences[table]
        for row in rows:
            id_ = row["id"]
            tbl[id_] = row
            seq = max(seq, id_)
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
        self, table: str, updates: list[tuple[int, dict[str, Any]]]
    ) -> None:
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
        return self._tables.get(table, {}).get(id_)

    def get_rows(self, table: str, ids: list[int]) -> dict[int, dict[str, Any]]:
        tbl = self._tables.get(table, {})
        result: dict[int, dict[str, Any]] = {}
        for id_ in ids:
            row = tbl.get(id_)
            if row is not None:
                result[id_] = row
        return result

    def contains_ids(self, table: str, ids: list[int]) -> set[int]:
        tbl = self._tables.get(table, {})
        return {id_ for id_ in ids if id_ in tbl}

    def table_ids(self, table: str) -> list[int]:
        return list(self._tables.get(table, {}).keys())

    def row_count(self, table: str) -> int:
        return len(self._tables.get(table, {}))

    def search_rows(
        self,
        table: str,
        column: str,
        value: Any,
        operator: str = "=",
    ) -> list[int]:
        op_fn = _OPERATORS.get(operator)
        if op_fn is None:
            raise ValueError(f"Unsupported operator: {operator!r}")
        tbl = self._tables.get(table, {})
        return [id_ for id_, row in tbl.items() if op_fn(row.get(column), value)]

    def next_id(self, table: str) -> int:
        self._sequences[table] += 1
        return self._sequences[table]

    def __repr__(self) -> str:
        n_tables = len(self._tables)
        n_rows = sum(len(t) for t in self._tables.values())
        return f"<DictBackend tables={n_tables} rows={n_rows}>"
