from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from odoo.libs.debug_log import DebugLog

_debug = DebugLog(__name__)


class TransactionSchemaCache:
    __slots__ = ("_column_types", "_id_sequences", "_locked_tables")

    def __init__(self) -> None:
        self._id_sequences: dict[str, str] = {}
        self._column_types: dict[tuple[str, tuple[str, ...]], list[int]] = {}
        self._locked_tables: dict[str, int] = {}

    def __repr__(self) -> str:
        return (
            f"TransactionSchemaCache(sequences={len(self._id_sequences)},"
            f" column_types={len(self._column_types)},"
            f" locked={len(self._locked_tables)})"
        )

    @property
    def locked_tables(self) -> Mapping[str, int]:
        return MappingProxyType(self._locked_tables)

    def is_locked(self, table: str) -> bool:
        return table in self._locked_tables

    def mark_locked(self, table: str, depth: int) -> None:
        self._locked_tables.setdefault(table, depth)

    def release_locks_since_depth(self, depth: int) -> None:
        released = [table for table, d in self._locked_tables.items() if d >= depth]
        if not released:
            return
        _debug.lifecycle(
            "schema_cache.locks_released", depth=depth, tables=len(released)
        )
        for table in released:
            del self._locked_tables[table]
            self._id_sequences.pop(table, None)
        released_set = set(released)
        self._column_types = {
            key: types
            for key, types in self._column_types.items()
            if key[0] not in released_set
        }

    def get_id_sequence(self, table: str) -> str | None:
        return self._id_sequences.get(table)

    def set_id_sequence(self, table: str, seq_name: str) -> None:
        self._id_sequences[table] = seq_name

    def get_column_types(
        self, table: str, columns: list[str] | tuple[str, ...]
    ) -> list[int] | None:
        return self._column_types.get((table, tuple(columns)))

    def set_column_types(
        self,
        table: str,
        columns: list[str] | tuple[str, ...],
        types: list[int],
    ) -> None:
        self._column_types[table, tuple(columns)] = types

    def invalidate_catalog_facts(self) -> None:
        if _debug.lifecycle.enabled and (self._id_sequences or self._column_types):
            _debug.lifecycle(
                "schema_cache.catalog_facts_invalidated",
                sequences=len(self._id_sequences),
                column_types=len(self._column_types),
            )
        self._id_sequences.clear()
        self._column_types.clear()

    def clear(self) -> None:
        self.invalidate_catalog_facts()
        self._locked_tables.clear()
