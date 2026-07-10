"""Persistence backends — the seam between the ORM and where rows actually live.

Production CRUD targets PostgreSQL: it emits SQL inline in the model mixins
(``create``/``write``/``read``/``search``/``unlink``).  The DB-free test tier
(:mod:`odoo.orm.model_test_env`) instead keeps rows in an in-memory
:class:`~odoo.orm.components.storage.DictBackend`.

Historically the in-memory variant was inlined into every CRUD mixin behind
``if self.env.transaction.storage is not None:`` guards — a second persistence
implementation smeared across six hot-path files, naming a test-only concept in
production code.  :class:`InMemoryBackend` collects that variant in one place;
the mixins now ask :pyattr:`Environment.backend` for it and fall back to the SQL
path when it is ``None``.

``env.backend is None`` is the **PostgreSQL fast path**: production never
allocates a backend object, so the dispatch is a single attribute load with no
indirection.  An explicit backend object overrides the SQL default and owns the
in-memory equivalent of each operation.  This keeps the ORM hot path free while
giving the in-memory store a real, testable home and a clear extension point.
"""

from __future__ import annotations

import logging
import typing

from odoo.exceptions import LockError
from odoo.tools import Query, partition

from ..primitives import NewId

if typing.TYPE_CHECKING:
    from ..components.storage import DictBackend
    from ..domain import Domain
    from ..fields import Field
    from ..models.base import BaseModel

_logger = logging.getLogger("odoo.orm.backend")


@typing.runtime_checkable
class StorageBackend(typing.Protocol):
    """The persistence contract the CRUD mixins dispatch to.

    ``Environment.backend`` is ``None`` for the PostgreSQL fast path (the mixins
    then run SQL inline -- production never allocates a backend object) or a
    concrete :class:`StorageBackend` for the in-memory test tier. Making the
    contract explicit lets the type checker flag a backend that forgets a method,
    and lets ``test_backend_protocol`` assert every method has a dispatch site --
    the safeguard that turns "a new persistence op silently runs SQL against the
    in-memory store" from a latent bug into a failed test (as it did for the
    row-lock methods). ``supports_parent_store`` is an attribute, not a method.

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
        in-memory equivalent of SQL ``NULL``.
        """
        row_dicts: list[dict[str, typing.Any]] = []
        new_ids: list[int] = []
        for stored in stored_list:
            new_id = self.storage.next_id(model._table)
            row_dict: dict[str, typing.Any] = {"id": new_id}
            for fname, field in zip(columns, col_fields, strict=True):
                if fname in stored:
                    row_dict[fname] = field.convert_to_column_insert(
                        stored[fname], model, stored
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

        Plain values are stored as-is, skipping the JSONB merge the SQL path
        does for translated / company-dependent fields (enough for business
        tests, which is the only context this backend runs in).
        """
        updates = [(row[0], dict(zip(fnames, row[1:], strict=True))) for row in rows]
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
                        value = row.get(field.name)
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
                    field_cache[record_id] = convert(row[fname], sentinel)

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
