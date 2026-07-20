"""Process-global schema-lookup caches for bulk ``COPY``.

:meth:`Cursor.copy_from` needs two pieces of catalog metadata too expensive to
re-query per bulk insert: the id column's sequence name (for ``returning_ids``)
and the column type names (for binary COPY's ``set_types``).  Both are stable for
a schema's life, so they are memoized here.

One owner with an explicit ``get`` / ``set`` / ``clear`` contract keeps three
correctness rules in one place:

* **dbname keying** — one process serves several databases whose same-named
  tables may diverge, so every key is prefixed with the database name; a stale
  cross-DB entry can't poison another database's COPY.
* **never cache temp relations** — ``pg_temp_*`` tables are session-local but the
  keys are name-based, so a cached temp entry could be fed to another session's
  same-named temp or the permanent table it shadows.  ``set_*`` silently refuses
  them so the rule can't be forgotten.
* **race-free per-db clear** — invalidation runs concurrently with population, so
  :meth:`SchemaCache.clear` snapshots keys with ``list()`` before filtering and
  pops with ``pop(k, None)``.

Thread-safety relies only on individual dict ops being atomic, which holds under
the GIL and on free-threaded builds (PEP 703).  A get-then-set miss may race two
populators, but both compute the same value, so last-write-wins is correct.  No
lock is taken (it would span ``clear``'s iteration and could deadlock against
pool callbacks).  Verified free-threaded (24 threads on overlapping keys: zero
exceptions, zero wrong-value reads).
"""

from __future__ import annotations


class SchemaCache:
    """Owns the id-sequence and column-type caches used by ``copy_from``.

    A single process-global :data:`schema_cache` instance is shared by every
    cursor (the metadata is a property of the schema, and each key carries the
    dbname); see the module docstring.
    """

    __slots__ = ("_column_types", "_id_sequences")

    def __init__(self) -> None:
        # (dbname, table) -> sequence name for the id column.
        self._id_sequences: dict[tuple[str, str], str] = {}
        # (dbname, table, columns) -> list of PostgreSQL type names.
        self._column_types: dict[tuple[str, str, tuple[str, ...]], list[str]] = {}

    # -- id sequence (returning_ids) ---------------------------------------

    def get_id_sequence(self, dbname: str, table: str) -> str | None:
        """Return the cached id-column sequence name, or ``None`` on a miss."""
        return self._id_sequences.get((dbname, table))

    def set_id_sequence(self, dbname: str, table: str, seq_name: str) -> None:
        """Cache *seq_name* for ``(dbname, table)`` unless it is session-local.

        A ``pg_temp.<seq>`` name is per-session, so the name-based key would
        resolve it to the wrong (or a nonexistent) sequence in another session;
        such entries are silently skipped.
        """
        if not str(seq_name).startswith("pg_temp"):
            self._id_sequences[dbname, table] = seq_name

    # -- column types (binary COPY) ----------------------------------------

    def get_column_types(
        self, dbname: str, table: str, columns: list[str] | tuple[str, ...]
    ) -> list[str] | None:
        """Return the cached PG type names for *columns*, or ``None`` on a miss."""
        return self._column_types.get((dbname, table, tuple(columns)))

    def set_column_types(
        self,
        dbname: str,
        table: str,
        columns: list[str] | tuple[str, ...],
        types: list[str],
        *,
        namespace: str,
    ) -> None:
        """Cache *types* for ``(dbname, table, columns)`` unless temp.

        *namespace* is the relation's ``pg_namespace.nspname``; a ``pg_temp_*``
        relation is skipped so its types are never fed to another session's
        binary COPY via the name-based key.
        """
        if not namespace.startswith("pg_temp"):
            self._column_types[dbname, table, tuple(columns)] = types

    # -- invalidation ------------------------------------------------------

    def clear(self, dbname: str | None = None) -> None:
        """Drop cached lookups.

        :param dbname: only drop entries for this database; ``None`` drops all.
        """
        for cache in (self._column_types, self._id_sequences):
            if dbname is None:
                cache.clear()
            else:
                # Snapshot keys before filtering, pop(k, None) for concurrency —
                # see the module docstring.
                for key in [k for k in list(cache) if k[0] == dbname]:
                    cache.pop(key, None)


# Process-global singleton shared by all cursors.
schema_cache = SchemaCache()
