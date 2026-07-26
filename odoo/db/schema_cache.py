"""Transaction-scoped catalog facts for bulk ``COPY``.

:meth:`Cursor.copy_from` needs two pieces of catalog metadata that are too
expensive to re-query per batch: the id column's sequence name (for
``returning_ids``) and the column type OIDs (for binary COPY's ``set_types``).
Both are memoized here, on the cursor, for the duration of **one transaction**.

Why not process-global (which is what this cache used to be): those facts are
only authoritative while a lock conflicting with ``ACCESS EXCLUSIVE`` is held.
:meth:`~odoo.db.bulk._BulkAccessMixin._lock_table_for_bulk` therefore takes
``ROW EXCLUSIVE`` on the target table — the very lock ``COPY`` needs anyway —
*before* reading the catalog, and PostgreSQL keeps it until the transaction
ends.  No type-changing DDL can commit in between, so the facts stay true for
the rest of the transaction, and not one statement longer.

A cache that outlived the transaction had no such guarantee and would silently
feed pre-DDL types to a later binary COPY.  Three ways that happened:

* another session's ``ALTER`` committing while ``copy_from`` waited for its own
  lock — the read-then-COPY window is as long as the DDL transaction runs, not
  microseconds, and a same-width type change (``int4`` → ``date``) is written
  without any error;
* this cursor's own DDL being rolled back after the cache was populated, which
  left the process wedged: every later bulk insert on that table failed;
* any DDL from another worker, until registry signaling happened to drain.

Scoping the cache to the transaction that holds the lock removes all three by
construction.  That is also why no invalidation wiring is left in ``close_db``
/ ``drain_db`` / ``drain_all``: nothing survives a transaction to go stale, so
there is no process-global schema state to clear.

Temp relations need no special handling either.  The old cache had to refuse
``pg_temp_*`` entries because its keys were name-based and shared across
sessions; a per-cursor cache cannot leak one session's temp relation into
another.
"""

from __future__ import annotations


class TransactionSchemaCache:
    """Catalog facts one cursor may reuse until its transaction ends.

    Deliberately **not** a process-global singleton (see the module docstring):
    one instance per :class:`~odoo.db.cursor.Cursor`, reset by ``commit()`` /
    ``rollback()`` and by schema-changing DDL run through this cursor.
    """

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
        """Return the cached id-column sequence name, or ``None`` on a miss."""
        return self._id_sequences.get(table)

    def set_id_sequence(self, table: str, seq_name: str) -> None:
        """Cache *seq_name* for *table* for the rest of this transaction."""
        self._id_sequences[table] = seq_name

    def get_column_types(
        self, table: str, columns: list[str] | tuple[str, ...]
    ) -> list[int] | None:
        """Return the cached PG type OIDs for *columns*, or ``None`` on a miss."""
        return self._column_types.get((table, tuple(columns)))

    def set_column_types(
        self,
        table: str,
        columns: list[str] | tuple[str, ...],
        types: list[int],
    ) -> None:
        """Cache *types* for ``(table, columns)`` for the rest of this transaction."""
        self._column_types[table, tuple(columns)] = types

    def clear_catalog_facts(self) -> None:
        """Drop the memoized catalog reads, keeping the table-lock ledger.

        For when a schema change lands but the transaction continues
        (:meth:`Cursor.discard_cached_plans`).  ``locked_tables`` is deliberately
        kept: PostgreSQL holds a ``ROW EXCLUSIVE`` lock to the end of the
        transaction, and DDL does not end one, so the lock this cursor already
        took is still held and re-issuing ``LOCK TABLE`` would be a wasted
        round-trip.  The catalog facts, by contrast, are exactly what the DDL
        may have invalidated.
        """
        self._id_sequences.clear()
        self._column_types.clear()

    def clear(self) -> None:
        """Drop every cached fact, including the table-lock ledger.

        Called where the locks themselves are gone: at each transaction boundary
        (``commit`` / ``rollback``) and on ``ROLLBACK TO SAVEPOINT``, which
        releases the locks acquired inside the savepoint.
        """
        self.clear_catalog_facts()
        self.locked_tables.clear()
