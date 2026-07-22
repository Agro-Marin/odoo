"""Backward-compatible ``env.cache`` wrapper.

:class:`Cache` provides the legacy ``env.cache.get(record, field)`` API,
delegating to :class:`~odoo.orm.components.core.OrmCore` /
:class:`~odoo.orm.components.cache.FieldCache`.  New ORM code uses ``env._core``.
"""

import contextlib
import logging
import typing
from pprint import pformat

from odoo.exceptions import CacheMiss
from odoo.tools import SQL, OrderedSet, Query, frozendict
from odoo.tools.misc import PENDING, SENTINEL

if typing.TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Iterator

    from .._typing import BaseModel, Field
    from ..primitives import IdType
    from .transaction import Transaction

_logger = logging.getLogger("odoo.api")

EMPTY_DICT = frozendict()  # type: ignore[var-annotated]


class Cache:
    """Cache of records (backward-compat wrapper).

    .. deprecated:: 19.0
        Internal ORM code should use ``env._core``
        (:class:`~odoo.orm.components.core.OrmCore`); external code should
        migrate to ``env._core`` or ``env.invalidate_all()`` /
        ``env.flush_all()``.

    The cache maps ``(record, field) -> value``, partitioned by field then by
    record (so "which records have a value" / "invalidate a field on all
    records" are fast).  Context-dependent fields key on the environment too.

    Entries may be marked "dirty": pending DB writes, only meaningful for stored
    fields.  A dirty context-dependent field marks *all* of the record's values
    for that field dirty; the to-be-written values must live in a context where
    all the field's context keys are ``None``.
    """

    __slots__ = ("transaction",)

    def __init__(self, transaction: Transaction):
        self.transaction = transaction

    def __repr__(self) -> str:
        # debugging: show cache content with dirty flags as stars
        data: dict[Field, dict] = {}
        core = self.transaction.core
        for field, field_cache in sorted(
            core.iter_field_items(), key=lambda item: str(item[0])
        ):
            dirty_ids = core.get_dirty(field) or ()
            if field in self.transaction.registry.field_depends_context:
                data[field] = {
                    key: {
                        Starred(id_) if id_ in dirty_ids else id_: (
                            val if field.type != "binary" else "<binary>"
                        )
                        for id_, val in key_cache.items()
                    }
                    for key, key_cache in field_cache.items()
                }
            else:
                data[field] = {
                    Starred(id_) if id_ in dirty_ids else id_: (
                        val if field.type != "binary" else "<binary>"
                    )
                    for id_, val in field_cache.items()
                }
        return repr(data)

    def _get_field_cache(
        self, model: BaseModel, field: Field
    ) -> typing.Mapping[IdType, typing.Any]:
        """Return the field cache for reading (not modification)."""
        return self._set_field_cache(model, field)

    def _set_field_cache(
        self, model: BaseModel, field: Field
    ) -> dict[IdType, typing.Any]:
        """Return the field cache for modification."""
        return field._get_cache(model.env)

    def contains(self, record: BaseModel, field: Field) -> bool:
        """Return whether ``record`` has a value for ``field``."""
        return record.id in self._get_field_cache(record, field)

    def get(self, record: BaseModel, field: Field, default=SENTINEL):
        """Return the value of ``field`` for ``record``."""
        try:
            field_cache = self._get_field_cache(record, field)
            return field_cache[record._ids[0]]
        except (KeyError, IndexError):
            # IndexError: empty recordset (record._ids == ()); treat as a miss
            # rather than leaking an opaque IndexError past the default/CacheMiss
            # contract.
            if default is SENTINEL:
                raise CacheMiss(record, field) from None
            return default

    def set(
        self,
        record: BaseModel,
        field: Field,
        value: typing.Any,
        dirty: bool = False,
    ) -> None:
        """Set the value of ``field`` for ``record``.

        A clean field can be made dirty, not the reverse: updating a dirty field
        without ``dirty=True`` raises.

        :param dirty: whether to mark ``field`` dirty on ``record`` after update.
        """
        field._update_cache(record, value, dirty=dirty)

    def update(
        self,
        records: BaseModel,
        field: Field,
        values: Iterable,
        dirty: bool = False,
    ) -> None:
        """Set the values of ``field`` for several ``records``.

        A clean field can be made dirty, not the reverse: updating a dirty field
        without ``dirty=True`` raises.

        :param dirty: whether to mark ``field`` dirty on the records after update.
        """
        for record, value in zip(records, values, strict=False):
            field._update_cache(record, value, dirty=dirty)

    def update_raw(
        self,
        records: BaseModel,
        field: Field,
        values: Iterable,
        dirty: bool = False,
    ) -> None:
        """Set already-cache-formatted ``values`` for ``records`` directly.

        Like :meth:`update`, but writes the values straight into the field
        cache without the per-record clean/dirty guard or any conversion: the
        caller supplies values already in cache format and parallel to
        ``records._ids``.  Used for fast cache population (copying values
        between records) and for seeding a to-be-flushed value.

        :param dirty: mark ``field`` dirty on the records (stored column fields
            only, mirroring :meth:`Field._update_cache`); the values must then
            be in the field's null-context form.
        """
        field_cache = self._set_field_cache(records, field)
        field_cache.update(zip(records._ids, values, strict=False))
        if field.is_column and dirty:
            self.transaction.core.mark_dirty(
                field, [id_ for id_ in records._ids if id_]
            )

    def remove(self, record: BaseModel, field: Field) -> None:
        """Remove the value of ``field`` for ``record``.

        Removing a dirty entry would lose the pending write, so it is rejected.
        ``raise`` (not ``assert``) so the check holds under ``python -O`` too.
        """
        if record.id in (self.transaction.core.get_dirty(field) or ()):
            raise ValueError(
                f"Cannot remove cache entry for dirty field "
                f"{field!r} on record {record}: pending write would be lost"
            )
        try:
            field_cache = self._set_field_cache(record, field)
            del field_cache[record._ids[0]]
        except KeyError:
            pass

    def get_values(self, records: BaseModel, field: Field) -> Iterator[typing.Any]:
        """Return the cached values of ``field`` for ``records``."""
        field_cache = self._get_field_cache(records, field)
        for record_id in records._ids:
            with contextlib.suppress(KeyError):
                yield field_cache[record_id]

    def get_fields(self, record: BaseModel) -> Iterator[Field]:
        """Return the fields with a value for ``record``."""
        for name, field in record._fields.items():
            if name != "id" and record.id in self._get_field_cache(record, field):
                yield field

    def get_records(
        self, model: BaseModel, field: Field, all_contexts: bool = False
    ) -> BaseModel:
        """Return the records of ``model`` that have a value for ``field``.

        Checks the current context of ``model``, or all contexts when
        ``all_contexts`` is true.
        """
        ids: Iterable
        if all_contexts and field in model.pool.field_depends_context:
            field_cache = self.transaction.core.get_field_data_or_none(field) or EMPTY_DICT
            ids = OrderedSet(
                id_ for sub_cache in field_cache.values() for id_ in sub_cache
            )
        else:
            ids = self._get_field_cache(model, field)
        return model.browse(ids)

    def get_missing_ids(self, records: BaseModel, field: Field) -> Iterator[IdType]:
        """Return the ids of ``records`` that have no value for ``field``."""
        return field._cache_missing_ids(records)

    def invalidate(
        self,
        spec: Collection[tuple[Field, Collection[IdType] | None]] | None = None,
    ) -> None:
        """Invalidate the cache, partially or totally depending on ``spec``.

        ``spec`` is ``[(field, ids), (field, None), ...]``; ``None`` ids means
        the whole field.  Invalidating a context-dependent field for a record
        invalidates that field on the record in all environments.

        Unsafe: invalidating a dirty field drops the value to be written.
        """
        if spec is None:
            self.transaction.invalidate_field_data()
            return
        env = next(iter(self.transaction.envs), None)
        if env is None:
            # All envs GC'd: without one we cannot invalidate context-aware
            # caches.  Return a no-op (logged at debug) rather than raising.
            _logger.debug(
                "Cache.invalidate: skipped %d entries — no environments left "
                "in transaction (all GC'd)",
                len(spec) if hasattr(spec, "__len__") else -1,
            )
            return
        for field, ids in spec:
            field._invalidate_cache(env, ids)

    def clear(self):
        """Invalidate the cache and its dirty flags.

        ``core.clear_cache()`` empties the underlying ``FieldCache`` (data +
        dirty + patches) but leaves each environment's ``_field_cache_memo``
        pointing at the now-detached per-field dicts, so a subsequent read
        serves a stale value and a subsequent write flushes into a dict the
        cache no longer knows about (``RuntimeError`` at flush).  Purge the
        memos too, keeping the two in sync — mirroring ``Transaction.clear()``
        without discarding pending computes (this is the recordset-level cache
        API, not a full transaction reset).
        """
        txn = self.transaction
        txn.core.clear_cache()
        for env in txn.envs:
            with contextlib.suppress(AttributeError):
                del env._field_cache_memo

    def check(self, env) -> None:
        """Check the consistency of the cache for the given environment."""
        depends_context = env.registry.field_depends_context
        core = self.transaction.core
        invalids = []

        def process(model: BaseModel, field: Field, field_cache):
            # ignore new records, records to flush, and PENDING placeholders
            dirty_ids = core.get_dirty(field) or ()
            _pending = PENDING
            ids = [
                id_
                for id_ in field_cache
                if id_ and id_ not in dirty_ids and field_cache[id_] is not _pending
            ]
            if not ids:
                return

            # select the column for the given ids
            query = Query(env, model._table, model._table_sql)
            sql_id = SQL.identifier(model._table, "id")
            sql_field = model._field_to_sql(model._table, field.name, query)
            if field.type == "binary" and (
                model.env.context.get("bin_size")
                or model.env.context.get("bin_size_" + field.name)
            ):
                sql_field = SQL("pg_size_pretty(length(%s)::bigint)", sql_field)
            query.add_where(SQL("%s = ANY(%s)", sql_id, list(ids)))
            env.cr.execute(query.select(sql_id, sql_field))

            # compare returned values with corresponding values in cache
            for id_, value in env.cr.fetchall():
                cached = field_cache[id_]
                if value == cached or (not value and not cached):
                    continue
                invalids.append(
                    (
                        model.browse((id_,)),
                        field,
                        {"cached": cached, "fetched": value},
                    )
                )

        for field, field_cache in core.iter_field_items():
            # check column fields only
            if (
                not field.store
                or not field.column_type
                or field.translate
                or field.company_dependent
            ):
                continue

            model = env[field.model_name]
            if field in depends_context:
                for context_keys, inner_cache in field_cache.items():
                    # cache_keys are built from depends_context — their length
                    # is invariant.  strict=True surfaces any future shape drift.
                    context = dict(
                        zip(depends_context[field], context_keys, strict=True)
                    )
                    if "company" in context:
                        # the cache key 'company' actually comes from context
                        # key 'allowed_company_ids' (see property env.company
                        # and method env.cache_key())
                        context["allowed_company_ids"] = [context.pop("company")]
                    process(model.with_context(context), field, inner_cache)
            else:
                process(model, field, field_cache)

        if invalids:
            _logger.warning("Invalid cache: %s", pformat(invalids))


class Starred:
    """Wrap a value so its ``repr`` gets a star suffix."""

    __slots__ = ["value"]

    def __init__(self, value):
        self.value = value

    def __repr__(self):
        return f"{self.value!r}*"
