"""Persistence backends — the seam between the ORM and where rows actually live.

Production CRUD targets PostgreSQL: it emits SQL inline in the model mixins
(``create``/``write``/``read``/``search``/``unlink``).  The DB-free test tier
(:mod:`odoo.orm.model_test_env`) instead keeps rows in an in-memory
:class:`~odoo.orm.components.storage.DictBackend`.

:class:`InMemoryBackend` collects the in-memory variant of each operation in one
place; the mixins ask :pyattr:`Environment.backend` for it and fall back to the
SQL path when it is ``None``.

``env.backend is None`` is the **PostgreSQL fast path**: production never
allocates a backend object, so dispatch is a single attribute load. An explicit
backend object overrides the SQL default and owns the in-memory equivalent of
each operation.
"""

from __future__ import annotations

import logging
import typing

from psycopg.types.json import Json, Jsonb

from odoo.exceptions import LockError
from odoo.tools import Query, partition

from ..primitives import NewId

if typing.TYPE_CHECKING:
    from ..components.storage import DictBackend
    from ..domain import Domain
    from ..fields import Field
    from ..models.base import BaseModel

_logger = logging.getLogger("odoo.orm.backend")


def _unwrap_json(value: typing.Any) -> typing.Any:
    """Return the plain Python object behind a psycopg JSON adapter.

    ``convert_to_column_insert`` / ``get_column_update`` wrap translated,
    company-dependent, and Json-typed values in :class:`psycopg.types.json.Json`
    (an *adapter* that psycopg serializes on the wire, meaningless to Python
    code).  A real ``jsonb`` column read returns the parsed object (a plain
    dict), so the in-memory store must hold the unwrapped ``value.obj`` —
    otherwise a fetch after ``invalidate_all()`` would hand ``convert_to_cache``
    a ``Json({'en_US': 'Hello'})`` wrapper instead of the dict.
    """
    if isinstance(value, (Json, Jsonb)):
        return value.obj
    return value


def _column_read_value(field: Field, value: typing.Any, env) -> typing.Any:
    """Project a stored column value the way the SQL ``SELECT`` term would.

    Most fields select the raw column, but translated fields select
    ``COALESCE(col->>lang, ..., col->>'en_US')`` (see ``Char.to_sql``), so the
    stored ``{lang: value}`` dict must be reduced to the scalar for the env's
    language before it is handed to ``convert_to_cache`` — exactly what the
    fetched SQL row would contain.  (With ``prefetch_langs`` the SQL selects
    the full jsonb dict, so the dict passes through unchanged.)
    """
    if (
        field.translate
        and isinstance(value, dict)
        and not env.context.get("prefetch_langs")
    ):
        for lang in field.get_translation_fallback_langs(env):
            scalar = value.get(lang)
            if scalar is not None:
                return scalar
        return None
    return value


@typing.runtime_checkable
class StorageBackend(typing.Protocol):
    """The persistence contract the CRUD mixins dispatch to.

    ``Environment.backend`` is ``None`` for the PostgreSQL fast path (SQL inline,
    no backend object) or a concrete :class:`StorageBackend` for the in-memory
    test tier. Making the contract explicit lets the type checker flag a backend
    that forgets a method, and lets ``test_backend_protocol`` assert every method
    has a dispatch site -- so a new persistence op that silently runs SQL against
    the in-memory store fails a test instead of being a latent bug (as it did for
    the row-lock methods). ``supports_parent_store`` is an attribute, not a method.

    ``supports_record_rules`` declares whether ``search()`` enforces ``ir.rule``
    record rules. The SQL path always does (via the security domain in
    ``SearchMixin._search``); the in-memory tier dispatches before that domain is
    applied and evaluates rules with different (non-sudo, no related-field SQL)
    semantics, so it declares ``False`` — tests needing record-rule behaviour
    must use the DB tier, and can assert on this flag rather than silently
    getting a false green.
    """

    supports_parent_store: bool
    supports_record_rules: bool

    def create_rows(
        self,
        model: BaseModel,
        stored_list: list[dict[str, typing.Any]],
        columns: list[str],
        col_fields: list[Field],
    ) -> list[int]: ...

    def update_rows(
        self, model: BaseModel, fnames: tuple[str, ...], rows: list[tuple]
    ) -> None: ...

    def fetch(
        self,
        model: BaseModel,
        query: Query,
        column_fields: typing.Iterable[Field],
        other_fields: typing.Iterable[Field],
    ) -> BaseModel: ...

    def search(
        self,
        model: BaseModel,
        domain: Domain,
        offset: int,
        limit: int | None,
        order: str | None,
    ) -> Query: ...

    def as_query(self, model: BaseModel, ordered: bool = True) -> Query: ...

    def existing_ids(self, model: BaseModel, ids: typing.Iterable[int]) -> set[int]: ...

    def lock_for_update(
        self, model: BaseModel, *, allow_referencing: bool = False
    ) -> None: ...

    def try_lock_for_update(
        self,
        model: BaseModel,
        *,
        allow_referencing: bool = False,
        limit: int | None = None,
    ) -> BaseModel: ...

    def delete(
        self,
        model: BaseModel,
        sub_ids: typing.Iterable[int],
        Data: BaseModel,
        Attachment: BaseModel,
    ) -> tuple[BaseModel, BaseModel]: ...

    def read_m2m_pairs(
        self,
        model: BaseModel,
        relation: str,
        column1: str,
        column2: str,
        ids: typing.Collection[int],
    ) -> list[tuple[int, int]]: ...

    def link_m2m_pairs(
        self,
        model: BaseModel,
        relation: str,
        column1: str,
        column2: str,
        pairs: typing.Iterable[tuple[int, int]],
    ) -> None: ...

    def unlink_m2m_pairs(
        self,
        model: BaseModel,
        relation: str,
        column1: str,
        column2: str,
        pairs: typing.Iterable[tuple[int, int]],
    ) -> None: ...


class InMemoryBackend:
    """CRUD against an in-memory :class:`DictBackend` instead of PostgreSQL.

    Every method takes the operating ``model`` (a recordset) as its first
    argument and reuses the model's own ORM machinery (``browse``,
    ``filtered_domain``, field conversion, the cache facade); only the row I/O
    is redirected to :pyattr:`storage`.  Selected by :pyattr:`Environment.backend`
    whenever a transaction was opened with a storage backend.
    """

    #: This backend has no hierarchical-tree support (``parent_path``); the
    #: ``_parent_store`` maintenance in ``create``/``write`` is skipped for it.
    supports_parent_store: bool = False

    #: ``search()`` does NOT enforce ir.rule record rules: dispatch happens before
    #: the security domain is applied (see ``SearchMixin._search``). Tests that
    #: depend on record-rule filtering must use the DB tier.
    supports_record_rules: bool = False

    __slots__ = ("storage",)

    def __init__(self, storage: DictBackend):
        self.storage = storage

    # -- create -------------------------------------------------------------
    def create_rows(
        self,
        model: BaseModel,
        stored_list: list[dict[str, typing.Any]],
        columns: list[str],
        col_fields: list[Field],
    ) -> list[int]:
        """Insert one row per entry in ``stored_list``; return the new ids.

        Values are converted exactly as the SQL ``INSERT`` path does (via
        ``convert_to_column_insert``); missing columns default to ``None``, the
        in-memory equivalent of SQL ``NULL``.  psycopg ``Json`` adapters
        (translated / company-dependent / Json fields) are unwrapped at this
        storage boundary so a later fetch returns the parsed dict, exactly like
        a real ``jsonb`` column read (see :func:`_unwrap_json`).
        """
        row_dicts: list[dict[str, typing.Any]] = []
        new_ids: list[int] = []
        for stored in stored_list:
            new_id = self.storage.next_id(model._table)
            row_dict: dict[str, typing.Any] = {"id": new_id}
            for fname, field in zip(columns, col_fields, strict=True):
                if fname in stored:
                    row_dict[fname] = _unwrap_json(
                        field.convert_to_column_insert(stored[fname], model, stored)
                    )
                # Missing columns default to None (same as SQL NULL)
            row_dicts.append(row_dict)
            new_ids.append(new_id)
        self.storage.put_rows(model._table, row_dicts)
        return new_ids

    # -- write --------------------------------------------------------------
    def update_rows(
        self, model: BaseModel, fnames: tuple[str, ...], rows: list[tuple]
    ) -> None:
        """Apply an UPDATE-equivalent for a group of records sharing ``fnames``.

        Values arrive in SQL-parameter shape (``get_column_update``); psycopg
        ``Json`` adapters are unwrapped so the stored shape is always the plain
        parsed object, consistent with :meth:`create_rows` and with what a real
        ``jsonb`` column read returns.

        Translated (``translate is True``) values are *partial* ``{lang: value}``
        dicts; mirror the SQL path's merge
        (``COALESCE(col, {'en_US': first(new)}) || new``) against the currently
        stored dict.  Company-dependent values get the same merge minus the
        fallback-pruning JOIN against ``ir.default`` (the pruned entries equal
        the fallback, so reads are unaffected; only the stored shape diverges).
        """
        fields_map = model._fields
        updates = []
        for row in rows:
            id_ = row[0]
            values: dict[str, typing.Any] = {}
            for fname, value in zip(fnames, row[1:], strict=True):
                value = _unwrap_json(value)
                field = fields_map.get(fname)
                if (
                    value is not None
                    and field is not None
                    and (field.translate is True or field.company_dependent)
                    and isinstance(value, dict)
                ):
                    old_row = self.storage.get_row(model._table, id_)
                    old = old_row.get(fname) if old_row else None
                    if field.translate is True and not isinstance(old, dict):
                        # SQL: COALESCE(col, jsonb_build_object('en_US',
                        # jsonb_path_query_first(new, '$.*')))
                        old = {"en_US": next(iter(value.values()))}
                    if isinstance(old, dict):
                        value = {**old, **value}
                values[fname] = value
            updates.append((id_, values))
        self.storage.upsert_rows(model._table, updates)

    # -- read ---------------------------------------------------------------
    def fetch(
        self,
        model: BaseModel,
        query: Query,
        column_fields: typing.Iterable[Field],
        other_fields: typing.Iterable[Field],
    ) -> BaseModel:
        """Load ``column_fields`` from storage into cache; return the records.

        Ids come from the resolved ``query`` (produced by :meth:`search` /
        :meth:`as_query`); when unresolved, fall back to the table's known ids.
        """
        result_ids = query._ids
        if result_ids is None:
            # Query not resolved yet: fall back to the table's known IDs.
            result_ids = tuple(self.storage.table_ids(model._table))

        if not result_ids:
            return model.browse()

        fetched = model.browse(result_ids)
        column_fields = list(column_fields)
        if column_fields:
            # Pre-resolve field caches once.  Context-dependent fields may
            # fail (env.company unavailable) — write to base cache.
            env = model.env
            _fdc = env._field_depends_context
            field_caches: dict = {}
            for field in column_fields:
                if field not in _fdc:
                    field_caches[field] = env._core.get_field_data(field)
                else:
                    # cache_key may fail to resolve when the env is not fully
                    # seeded (DictBackend tests).  Narrow the catch (as the
                    # sibling ``search`` does) so genuine _get_cache / cache_key
                    # bugs surface instead of being silently swallowed.
                    try:
                        field_caches[field] = field._get_cache(env)
                    except (KeyError, AttributeError, TypeError) as e:
                        _logger.debug(
                            "DictBackend cache load skipped %s.%s: %s",
                            model._name,
                            field.name,
                            e,
                        )
                        field_caches[field] = env._core.get_field_data(field)
            for record_id in result_ids:
                row = self.storage.get_row(model._table, record_id)
                if row is not None:
                    for field in column_fields:
                        value = _column_read_value(field, row.get(field.name), env)
                        fc = field_caches[field]
                        fc.setdefault(
                            record_id,
                            field.convert_to_cache(value, fetched),
                        )

        # process non-column fields
        if fetched:
            for field in other_fields:
                field.read(fetched)
        return fetched

    # -- search -------------------------------------------------------------
    def search(
        self,
        model: BaseModel,
        domain: Domain,
        offset: int,
        limit: int | None,
        order: str | None,
    ) -> Query:
        """Evaluate ``domain`` against storage using Python predicates.

        Fetches all record ids from storage, loads values into cache, then
        evaluates the domain in pure Python via ``filtered_domain()``.

        :return: a :class:`Query` with ``_ids`` set to matching record ids
        """
        # Flush pending writes first.  The PostgreSQL path flushes implicitly in
        # execute_query; the in-memory path must do it explicitly, else step 2
        # would overwrite dirty cache values from stale storage rows.
        model.env.flush_all()

        all_ids = self.storage.table_ids(model._table)
        if not all_ids:
            return model.browse()._as_query(ordered=False)

        # Load storage values into cache, batched by field to avoid per-record
        # browse() allocations and per-cell method overhead.
        all_records = model.browse(all_ids)
        rows = self.storage.get_rows(model._table, all_ids)

        # Pre-resolve storable fields and their cache dicts once.  For
        # context-dependent fields, _get_cache() needs env.company, which may be
        # absent in DictBackend tests; use field_data() directly otherwise.
        env = model.env
        fields_meta = model._fields
        _fdc = env._field_depends_context
        storable: list[tuple] = []  # (fname, field, field_cache)
        # Use a single sentinel browse record for convert_to_cache calls.
        # all_ids is non-empty here (guarded by the early return above).
        sentinel = model.browse(all_ids[0])
        for fname, field in fields_meta.items():
            if fname != "id" and field.store and field.column_type:
                if field not in _fdc:
                    storable.append((fname, field, env._core.get_field_data(field)))
                else:
                    # cache_key may fail to resolve when the env is not fully
                    # seeded (DictBackend tests).  Narrow the catch so genuine
                    # _get_cache / cache_key bugs surface instead of silenced.
                    try:
                        storable.append((fname, field, field._get_cache(env)))
                    except (KeyError, AttributeError, TypeError) as e:
                        _logger.debug(
                            "DictBackend cache load skipped %s.%s: %s",
                            model._name,
                            fname,
                            e,
                        )

        # Batch-load directly into cache dicts (fields outer, records inner).
        for fname, field, field_cache in storable:
            convert = field.convert_to_cache
            for record_id in all_ids:
                row = rows.get(record_id)
                if row is not None and fname in row:
                    value = _column_read_value(field, row[fname], env)
                    field_cache[record_id] = convert(value, sentinel)

        if not domain.is_true():
            matching = all_records.filtered_domain(domain)
        else:
            matching = all_records

        if order:
            matching = matching.sorted(key=order)

        ids = matching._ids
        if offset:
            ids = ids[offset:]
        if limit is not None and limit is not False:
            ids = ids[:limit]

        query = Query(model.env, model._table, model._table_sql)
        query._ids = tuple(ids)
        return query

    def as_query(self, model: BaseModel, ordered: bool = True) -> Query:
        """Return a :class:`Query` whose result is exactly ``model``'s ids.

        Ids are set directly; there is no SQL ``unnest`` to emit in memory.
        """
        query = Query(model.env, model._table, model._table_sql)
        query._ids = tuple(model._ids)
        return query

    def existing_ids(self, model: BaseModel, ids: typing.Iterable[int]) -> set[int]:
        """Return the subset of real ``ids`` that currently exist in storage."""
        return set(self.storage.contains_ids(model._table, ids))

    # -- lock ---------------------------------------------------------------
    def lock_for_update(
        self, model: BaseModel, *, allow_referencing: bool = False
    ) -> None:
        """In-memory equivalent of ``SELECT ... FOR UPDATE``.

        There are no concurrent transactions to contend with, so a row "locks"
        iff it exists; mirror the SQL path's ``LockError`` when some requested
        real id is absent.
        """
        ids = {id_ for id_ in model._ids if id_}
        if not ids:
            return
        if len(self.storage.contains_ids(model._table, ids)) != len(ids):
            raise LockError(model.env._("Cannot grab a lock on records"))

    def try_lock_for_update(
        self,
        model: BaseModel,
        *,
        allow_referencing: bool = False,
        limit: int | None = None,
    ) -> BaseModel:
        """In-memory equivalent of ``FOR UPDATE SKIP LOCKED``.

        Every existing row is lockable (no concurrent lockers), so return the
        requested records that exist, in id order, capped at ``limit``.
        """
        new_ids, real = partition(lambda i: isinstance(i, NewId), model._ids)
        lockable = self.storage.contains_ids(model._table, real) | set(new_ids)
        locked = [i for i in model._ids if i in lockable]
        if limit is not None:
            locked = locked[:limit]
        return model.browse(locked)

    # -- unlink -------------------------------------------------------------
    def delete(
        self,
        model: BaseModel,
        sub_ids: typing.Iterable[int],
        Data: BaseModel,
        Attachment: BaseModel,
    ) -> tuple[BaseModel, BaseModel]:
        """Delete rows from storage.

        Skips the ir.model.data / ir.attachment / company-dependent cleanup the
        SQL path performs — those models may not exist in a test context — and
        returns empty deferred-cleanup recordsets.
        """
        self.storage.delete_rows(model._table, list(sub_ids))
        return Data.browse(), Attachment.browse()

    # -- many2many relation tables -------------------------------------------
    #
    # Relation pairs are stored in the shared :class:`DictBackend` as rows
    # ``{column1: id1, column2: id2}`` under the relation-table name, keyed by
    # a synthetic auto-increment row id (pairs have no ``id`` column in SQL
    # either).  Because rows are keyed by *column name*, the two inverse
    # Many2many fields of one relation (which swap ``column1``/``column2``)
    # read and write the very same store, exactly like the single physical
    # table in PostgreSQL.  Iteration order is dict insertion order — the
    # closest in-memory analogue to the SQL table's physical order; the read
    # path re-orders by the comodel query anyway (see ``Many2many.read``).
    #
    # Known divergence from SQL: deleting a record does NOT cascade-delete its
    # relation rows (no foreign keys in memory).  Stale pairs are harmless:
    # reads filter both sides — ``column1`` by the requested record ids,
    # ``column2`` by the comodel query, which only returns live rows — and
    # ids are never reused (monotonic sequences).

    def _m2m_rows(self, relation: str):
        """Yield ``(row_id, row_dict)`` for every pair row, insertion-ordered."""
        for row_id in self.storage.table_ids(relation):
            row = self.storage.get_row(relation, row_id)
            if row is not None:
                yield row_id, row

    def read_m2m_pairs(
        self,
        model: BaseModel,
        relation: str,
        column1: str,
        column2: str,
        ids: typing.Collection[int],
    ) -> list[tuple[int, int]]:
        """Return the ``(column1, column2)`` pairs whose first id is in ``ids``.

        In-memory replacement for the relation-table half of the SQL read
        (``WHERE column1 = ANY(ids)``).  The other half — the JOIN against the
        comodel table that drops dead ids, applies the comodel domain, and
        orders by the comodel query — stays in ``Many2many.read``, which
        filters/orders these raw pairs against its backend-served comodel query.
        """
        wanted = set(ids)
        return [
            (row[column1], row[column2])
            for _row_id, row in self._m2m_rows(relation)
            if row.get(column1) in wanted
        ]

    def link_m2m_pairs(
        self,
        model: BaseModel,
        relation: str,
        column1: str,
        column2: str,
        pairs: typing.Iterable[tuple[int, int]],
    ) -> None:
        """Add relation pairs, skipping ones already present.

        Equivalent of ``INSERT INTO rel (col1, col2) VALUES ... ON CONFLICT DO
        NOTHING`` (including duplicates *within* ``pairs``).
        """
        existing = {
            (row.get(column1), row.get(column2))
            for _row_id, row in self._m2m_rows(relation)
        }
        to_insert = []
        for pair in pairs:
            pair = tuple(pair)
            if pair not in existing:
                existing.add(pair)
                to_insert.append(pair)
        if to_insert:
            self.storage.insert_rows(relation, [column1, column2], to_insert)

    def unlink_m2m_pairs(
        self,
        model: BaseModel,
        relation: str,
        column1: str,
        column2: str,
        pairs: typing.Iterable[tuple[int, int]],
    ) -> None:
        """Remove exactly the given relation pairs; absent pairs are no-ops.

        Equivalent of the SQL ``DELETE FROM rel WHERE (col1 = ANY(xs) AND col2
        = ANY(ys)) OR ...`` — whose cartesian groups are built so their union
        is exactly the pair set, so deleting the literal pairs matches it.
        """
        doomed = {tuple(pair) for pair in pairs}
        row_ids = [
            row_id
            for row_id, row in self._m2m_rows(relation)
            if (row.get(column1), row.get(column2)) in doomed
        ]
        if row_ids:
            self.storage.delete_rows(relation, row_ids)
