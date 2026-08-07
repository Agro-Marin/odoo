"""Backward-compatible ``env.cache`` wrapper.

:class:`Cache` provides the legacy ``env.cache.get(record, field)`` API,
delegating to :class:`~odoo.orm.components.core.OrmCore` /
:class:`~odoo.orm.components.cache.FieldCache`.  New ORM code uses ``env._core``.

Status (2026-07 audit): the write path IS still in production use —
``env.cache.set`` / ``update`` / ``update_raw`` are called by several addons
(website_sale ``website_snippet_filter``, iap ``iap_account``, base_account
``account_account``, hr ``hr_employee``, l10n_gcc_invoice ``account_move``,
calendar ``calendar_event``, html_editor ``ir_ui_view``), in addition to the
read helpers (``contains`` / ``get_records`` / ``get_values``) used by
``addons/account`` and the ``base``/``test_orm`` suites.  Do not demote the
shim (or its write methods) to test-only until those are migrated to the
supported seam (``Field._update_cache`` / ``env._core``).
"""

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
    """The ORM cache disagrees with the database (see :meth:`Cache.check`).

    An :class:`AssertionError` because it reports a broken framework invariant,
    not a user-facing condition, and so that it is not swallowed by handlers
    catching :class:`~odoo.exceptions.UserError`.
    """


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
        if dirty:
            for record, value in zip(records, values, strict=False):
                field._update_cache(record, value, dirty=True)
            return
        # The clean path is exactly ``_update_cache_items``: it resolves the
        # field cache and runs the dirty guard once for the batch instead of
        # rebuilding a singleton and re-checking the dirty set per record.
        field._update_cache_items(records.env, zip(records._ids, values, strict=False))

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
            ids = OrderedSet(
                self.transaction.core.all_cached_ids(field, context_dependent=True)
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

        Refuses to drop a field that still holds a pending write: this used to
        break the "dirty ⇒ value present" invariant, after which the next flush
        either wrote the re-fetched database value back over the pending one
        (silent loss) or died with "Could not find all values ... to flush".
        The check is the same one ``invalidate_model`` / ``invalidate_recordset``
        run — :meth:`OrmCore.find_pending_write` — so the modern and legacy
        entry points cannot disagree *about the guard*.  Flush first if you need
        both.

        They do differ in **scope**, and deliberately: ``invalidate_model`` /
        ``invalidate_recordset`` also invalidate each field's inverse (see
        ``CacheMixin._invalidate_cache``), this does not — it drops exactly the
        ``(field, ids)`` pairs it is handed.  Code migrating off this shim onto
        the model-level API therefore invalidates strictly more, which is safe;
        code moving the other way is not.
        """
        if spec is None:
            self.transaction.invalidate_field_data()
            return
        # Materialize up front: the guard pass and the work pass below both
        # walk `spec`, so a one-shot iterable would be exhausted by the guard
        # and invalidate nothing — succeeding silently.  Same reasoning as
        # OrmCore.invalidate and FieldCache.invalidate, which do this too.
        # Doing it here also lets the skip message report a real count.
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
        """Invalidate the cache and its dirty flags.

        Empties the underlying ``FieldCache`` (data + dirty + patches) without
        discarding pending computes — this is the recordset-level cache API, not
        a full transaction reset.  The per-environment ``_field_cache_memo``
        purge that must accompany it is fired by the cache itself (see
        :meth:`FieldCache.__init__`).
        """
        self.transaction.core.clear_cache()

    def check(self, env, *, raise_on_invalid: bool = True) -> list[tuple]:
        """Check that the cache agrees with the database, and report what does not.

        The only oracle for the cache-vs-database invariant.  It used to report
        exclusively through ``_logger.warning`` and return ``None``, so the five
        ``env.cache.check(env)`` calls in ``base/tests/test_api.py`` read as
        assertions while being unable to fail: a real divergence
        (``res.partner.write_date`` after a compute-driven flush) was logged on
        every run and never broke a build.

        :param raise_on_invalid: raise :class:`CacheInvalidError` when the cache
            disagrees with the database.  Pass ``False`` to inspect the
            divergences instead (diagnostics, tests that pin a known one).
        :return: the divergences as ``(records, field, {"cached": ..., "fetched": ...})``.
        :raises CacheInvalidError: if any divergence is found and
            *raise_on_invalid* is set.
        """
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
    """Wrap a value so its ``repr`` gets a star suffix."""

    __slots__ = ["value"]

    def __init__(self, value):
        self.value = value

    def __repr__(self):
        return f"{self.value!r}*"
