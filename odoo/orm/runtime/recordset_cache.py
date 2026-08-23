import contextlib
import logging
import typing
from pprint import pformat

from odoo.exceptions import CacheMiss
from odoo.tools import SQL, OrderedSet, Query
from odoo.tools.misc import PENDING, SENTINEL

if typing.TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Iterator

    from .._typing import BaseModel, Field
    from ..primitives import IdType
    from .transaction import Transaction

_logger = logging.getLogger("odoo.api")


class CacheInvalidError(AssertionError):
    pass


class Cache:
    """``env.cache`` — the **recordset-level** cache API.

    The ORM has two cache surfaces at different levels, and both are supported:

    * ``env._core`` (``OrmCore``) is **id-level**: ``get_value(field, record_id)``
      takes a raw id and the caller must know the storage layout.
    * ``env.cache`` — this class — is **recordset-level**: every method takes a
      recordset and resolves the field cache through its ``env``
      (``field._get_cache(model.env)``), so a caller never has to know that a
      context-dependent field is stored ``{cache_key: {id: value}}`` rather than
      ``{id: value}``, or that a term-translated one is reached through a
      ``LangProxyDict``.

    That difference is why ADR-0010 dropped its own step 4 (retire this class) on
    reassessment: a mechanical rewrite of the call sites onto ``_core`` would
    have got both layouts wrong. Shrinking this surface is a business-logic
    effort — eliminating addon cache-poking as an anti-pattern — not a handle
    swap.

    Until 2026-08-08 this module was named ``cache_compat.py``, and that name
    cost three separate corrections: this docstring, a dedicated test asserting
    the class "is not legacy", and a paragraph in ``doc/architecture/module.md``
    — each written because a reader had taken "compat" at face value. The name
    is now what the class is, so none of them has to say what it is not.
    """

    __slots__ = ("transaction",)

    def __init__(self, transaction: Transaction):
        self.transaction = transaction

    def __repr__(self) -> str:
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
                    for key, key_cache in core.iter_context_caches(field)
                }
            else:
                data[field] = {
                    Starred(id_) if id_ in dirty_ids else id_: (
                        val if field.type != "binary" else "<binary>"
                    )
                    for id_, val in field_cache.items()
                }
        return repr(data)

    def _field_cache(self, model: BaseModel, field: Field) -> dict[IdType, typing.Any]:
        """The dict this field's values live in, for ``model``'s environment.

        Was two methods, ``_get_field_cache`` and ``_set_field_cache``, with
        the first implemented as ``return self._set_field_cache(...)``: one
        behaviour, two names, two return annotations, and nine call sites
        below choosing between them by no rule anyone could state.
        """
        return field._get_cache(model.env)

    def contains(self, record: BaseModel, field: Field) -> bool:
        return record.id in self._field_cache(record, field)

    def get(self, record: BaseModel, field: Field, default=SENTINEL):
        try:
            field_cache = self._field_cache(record, field)
            return field_cache[record._ids[0]]
        except KeyError, IndexError:
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
        field._update_cache(record, value, dirty=dirty)

    def update(
        self,
        records: BaseModel,
        field: Field,
        values: Iterable,
        dirty: bool = False,
    ) -> None:
        if dirty:
            for record, value in zip(records, values, strict=False):
                field._update_cache(record, value, dirty=True)
            return
        field._update_cache_items(records.env, zip(records._ids, values, strict=False))

    def update_raw(
        self,
        records: BaseModel,
        field: Field,
        values: Iterable,
        dirty: bool = False,
    ) -> None:
        if not dirty and (
            found := self.transaction.core.find_pending_write((field,), records._ids)
        ):
            _field, overlap = found
            _logger.warning(
                "Cache.update_raw overwrote %s on records %s, which held a "
                "pending write that is now lost. Flush those records first, or "
                "pass dirty=True to declare that this value supersedes the "
                "pending one.",
                field,
                overlap[:10],
            )
        field_cache = self._field_cache(records, field)
        field_cache.update(zip(records._ids, values, strict=False))
        if field.is_column and dirty:
            self.transaction.core.mark_dirty(
                field, [id_ for id_ in records._ids if id_]
            )

    def remove(self, record: BaseModel, field: Field) -> None:
        if record.id in (self.transaction.core.get_dirty(field) or ()):
            raise ValueError(
                f"Cannot remove cache entry for dirty field "
                f"{field!r} on record {record}: pending write would be lost"
            )
        try:
            field_cache = self._field_cache(record, field)
            del field_cache[record._ids[0]]
        except KeyError:
            pass

    def get_values(self, records: BaseModel, field: Field) -> Iterator[typing.Any]:
        field_cache = self._field_cache(records, field)
        for record_id in records._ids:
            with contextlib.suppress(KeyError):
                yield field_cache[record_id]

    def get_fields(self, record: BaseModel) -> Iterator[Field]:
        for name, field in record._fields.items():
            if name != "id" and record.id in self._field_cache(record, field):
                yield field

    def get_records(
        self, model: BaseModel, field: Field, all_contexts: bool = False
    ) -> BaseModel:
        ids: Iterable
        if all_contexts and field in model.pool.field_depends_context:
            ids = OrderedSet(
                self.transaction.core.all_cached_ids(field, context_dependent=True)
            )
        else:
            ids = self._field_cache(model, field)
        return model.browse(ids)

    def get_missing_ids(self, records: BaseModel, field: Field) -> Iterator[IdType]:
        return field._cache_missing_ids(records)

    def invalidate(
        self,
        spec: Collection[tuple[Field, Collection[IdType] | None]] | None = None,
    ) -> None:
        if spec is None:
            self.transaction.invalidate_field_data()
            return
        spec = list(spec)
        env = next(iter(self.transaction.envs), None)
        if env is None:
            _logger.debug(
                "Cache.invalidate: skipped %d entries — no environments left "
                "in transaction (all GC'd)",
                len(spec),
            )
            return
        core = self.transaction.core
        for field, ids in spec:
            if (found := core.find_pending_write((field,), ids)) is not None:
                _field, overlap = found
                raise ValueError(
                    f"Cache.invalidate: refusing to drop {field} on records "
                    f"{overlap[:10]}; they hold a pending write that would be "
                    f"silently lost.  Flush those records first."
                )
        for field, ids in spec:
            field._invalidate_cache(env, ids)

    def clear(self):
        self.transaction.core.clear_cache()

    def check(self, env, *, raise_on_invalid: bool = True) -> list[tuple]:
        depends_context = env.registry.field_depends_context
        core = self.transaction.core
        invalids = []

        def process(model: BaseModel, field: Field, field_cache):
            dirty_ids = core.get_dirty(field) or ()
            _pending = PENDING
            ids = [
                id_
                for id_ in field_cache
                if id_ and id_ not in dirty_ids and field_cache[id_] is not _pending
            ]
            if not ids:
                return

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
            if (
                not field.store
                or not field.column_type
                or field.translate
                or field.company_dependent
            ):
                continue

            model = env[field.model_name]
            if field in depends_context:
                for context_keys, inner_cache in core.iter_context_caches(field):
                    context = dict(
                        zip(depends_context[field], context_keys, strict=True)
                    )
                    if "company" in context:
                        context["allowed_company_ids"] = [context.pop("company")]
                    process(model.with_context(context), field, inner_cache)
            else:
                process(model, field, field_cache)

        if invalids:
            _logger.warning("Invalid cache: %s", pformat(invalids))
            if raise_on_invalid:
                raise CacheInvalidError(
                    f"Cache does not match the database:\n{pformat(invalids)}"
                )
        return invalids


class Starred:
    __slots__ = ["value"]

    def __init__(self, value):
        self.value = value

    def __repr__(self):
        return f"{self.value!r}*"
