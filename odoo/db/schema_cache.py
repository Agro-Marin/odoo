from __future__ import annotations


class TransactionSchemaCache:
    __slots__ = ("_column_types", "_id_sequences", "_locked_tables")

    def __init__(self) -> None:
        self._id_sequences: dict[str, str] = {}
        self._column_types: dict[tuple[str, tuple[str, ...]], list[int]] = {}
        # table -> savepoint depth (0 = outside any savepoint) at lock time.
        self._locked_tables: dict[str, int] = {}

    def __repr__(self) -> str:
        return (
            f"TransactionSchemaCache(sequences={len(self._id_sequences)},"
            f" column_types={len(self._column_types)},"
            f" locked={len(self._locked_tables)})"
        )

    def is_locked(self, table: str) -> bool:
        return table in self._locked_tables

    def mark_locked(self, table: str, depth: int) -> None:
        self._locked_tables.setdefault(table, depth)

    def release_locks_since_depth(self, depth: int) -> None:
        """Drop the lock ledger entry -- and any cached catalog facts --
        for every table locked at savepoint depth `depth` or deeper.

        A ROLLBACK TO SAVEPOINT releases only the real PostgreSQL locks
        taken since that savepoint opened, not ones held from before it.
        Once such a table's lock is gone, a concurrent session's DDL may
        already be visible for it, so its cached facts must be dropped
        unconditionally -- regardless of whether *this* cursor issued any
        DDL. Tables locked at a shallower depth keep both their lock
        ledger entry and their cached facts untouched.
        """
        released = [table for table, d in self._locked_tables.items() if d >= depth]
        if not released:
            return
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
        self._id_sequences.clear()
        self._column_types.clear()

    def clear(self) -> None:
        self.invalidate_catalog_facts()
        self._locked_tables.clear()
