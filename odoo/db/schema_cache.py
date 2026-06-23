"""Process-global schema-lookup caches for bulk ``COPY``.

:meth:`Cursor.copy_from` needs two pieces of catalog metadata that are
expensive to re-query on every bulk insert: the id column's sequence name (for
``returning_ids``) and the exact PostgreSQL type names of the target columns
(for binary COPY's ``set_types``).  Both are stable for the life of a schema,
so they are memoized here.

Kept in its own module — and behind one small object rather than the historical
pair of bare module-global dicts — for the same reason :mod:`odoo.db.ddl` is
split out: this is correctness-sensitive shared mutable state (read/written by
``copy_from`` on request threads, invalidated by :mod:`odoo.db`'s ``close_db`` /
``drain_*`` on schema changes), and giving it one owner with an explicit
``get`` / ``set`` / ``clear`` contract keeps three rules that were previously
duplicated across call sites in a single, independently testable place:

* **dbname keying** — one process serves several databases whose same-named
  tables may have diverging schemas (staggered module versions).  Every key is
  prefixed with the database name, so a stale cross-DB entry can never poison
  another database's COPY (reproduced as ``ProtocolViolation`` /
  ``UndefinedTable`` before the keying existed).
* **never cache temp relations** — a temp table's name lives in a session-local
  ``pg_temp_*`` schema, but the keys are name-based; caching one session's temp
  sequence/types would hand them to another session whose same-named table is a
  *different* temp (wrong types) or the permanent table the name shadows
  (``pg_temp.<seq> does not exist``).  ``set_*`` silently refuses such entries
  so the rule cannot be forgotten at a call site.
* **race-free per-db clear** — invalidation runs concurrently with population
  (registry signalling vs. an in-flight COPY).  :meth:`SchemaCache.clear`
  snapshots the keys with ``list()`` before filtering, so it never raises
  "dictionary changed size during iteration", and pops with ``pop(k, None)`` so
  two concurrent clears of the same database cannot ``KeyError`` on the loser.

Thread-safety relies on CPython's GIL making single dict operations atomic — the
same guarantee the original module-global dicts relied on.  No lock is
introduced: a lock would have to be held across ``clear``'s iteration and could
deadlock against the pool's connection callbacks.
"""

from __future__ import annotations


class SchemaCache:
    """Owns the id-sequence and column-type caches used by ``copy_from``.

    A single process-global :data:`schema_cache` instance is shared by every
    cursor; see the module docstring for why the state is process-wide rather
    than per-pool (the metadata is a property of the database schema, identical
    for every connection, and already disambiguated by the dbname in each key).
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
                # snapshot the keys BEFORE filtering (a concurrent copy_from may
                # be inserting) and pop(k, None) (a concurrent clear of the same
                # db may have removed it) — see the module docstring.
                for key in [k for k in list(cache) if k[0] == dbname]:
                    cache.pop(key, None)


# Process-global singleton shared by all cursors.
schema_cache = SchemaCache()
