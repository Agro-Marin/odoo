from __future__ import annotations


class TransactionSchemaCache:
    __slots__ = ("_column_types", "_id_sequences", "locked_tables")

    def __init__(self) -> None:
        self._id_sequences: dict[str, str] = {}
        self._column_types: dict[tuple[str, tuple[str, ...]], list[int]] = {}
        self.locked_tables: set[str] = set()

    def __repr__(self) -> str:
        return (
            f"TransactionSchemaCache(sequences={len(self._id_sequences)},"
            f" column_types={len(self._column_types)},"
            f" locked={len(self.locked_tables)})"
        )

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

    def clear_catalog_facts(self) -> None:
        self._id_sequences.clear()
        self._column_types.clear()

    def clear(self) -> None:
        self.clear_catalog_facts()
        self.locked_tables.clear()
