"""Record cache and invalidation mixin for BaseModel.

Holds the pure in-memory record cache (:class:`RecordCache`) and cache
invalidation.  The DB-coupled recompute/flush machinery (``modified``,
``_recompute*``, ``flush*``, ``_flush``) lives in the sibling
:class:`~odoo.orm.models.mixins.recompute.RecomputeMixin` (``recompute.py``).
"""

import logging
import typing
from collections.abc import Collection, Mapping, Sequence

from ... import decorators as api
from ._model_stubs import _ModelStubs

_orm_cache = logging.getLogger("odoo.orm.cache")

if typing.TYPE_CHECKING:
    from ..._typing import IdType
    from ...fields.base import Field


class RecordCache(Mapping):
    """A mapping from field names to values, to read the cache of a record."""

    __slots__ = ["_record"]

    def __init__(self, record) -> None:
        # raise (not assert) so the contract holds under python -O.
        if len(record) != 1:
            raise ValueError(f"Unexpected RecordCache({record})")
        self._record = record

    def __contains__(self, name: object) -> bool:
        """Return whether `record` has a cached value for field ``name``."""
        record = self._record
        # honour the Mapping contract: an unknown name is "not contained",
        # not a KeyError (``name in record._cache`` must be a safe bool test).
        field = record._fields.get(name)
        return field is not None and record.id in field._get_cache(record.env)

    def __getitem__(self, name: str) -> object:
        """Return the cached value of field ``name`` for `record`."""
        record = self._record
        field = record._fields[name]
        return field._get_cache(record.env)[record.id]

    def __iter__(self) -> typing.Iterator[str]:
        """Iterate over the field names with a cached value."""
        record = self._record
        id_ = record.id
        env = record.env
        model_name = record._name
        depends_context = env._field_depends_context
        for field, cache in env._core.iter_field_items():
            if field.model_name != model_name:
                continue
            if field in depends_context:
                # context-dependent: cache is {context_key: {id: value}}
                cache = cache.get(env.cache_key(field))
                if cache and id_ in cache:
                    yield field.name
            elif id_ in cache:
                yield field.name

    def __len__(self) -> int:
        """Return the number of fields with a cached value."""
        return sum(1 for name in self)


class CacheMixin(_ModelStubs):
    """Mixin providing the record cache and its invalidation for recordsets.

    Recomputation and database flushing live in
    :class:`~odoo.orm.models.mixins.recompute.RecomputeMixin`.
    """

    __slots__ = ()

    @property
    def _cache(self) -> RecordCache:
        """Return the cache of ``self``, mapping field names to values."""
        return RecordCache(self)

    @api.private
    def invalidate_model(
        self, fnames: Collection[str] | None = None, flush: bool = True
    ) -> None:
        """Invalidate the cache of all records of ``self``'s model, when the
        cached values no longer correspond to the database values.  If the
        parameter is given, only the given fields are invalidated from cache.

        :param fnames: optional iterable of field names to invalidate
        :param flush: whether pending updates should be flushed before invalidation.
            It is ``True`` by default, which ensures cache consistency.
            Do not use this parameter unless you know what you are doing.
        """
        if flush:
            self.flush_model(fnames)
        self._invalidate_cache(fnames, flush=flush)
        if _orm_cache.isEnabledFor(logging.DEBUG):
            _orm_cache.debug("invalidate_model %s: fnames=%s", self._name, fnames)

    @api.private
    def invalidate_recordset(
        self, fnames: Collection[str] | None = None, flush: bool = True
    ) -> None:
        """Invalidate the cache of the records in ``self``, when the cached
        values no longer correspond to the database values.  If the parameter
        is given, only the given fields on ``self`` are invalidated from cache.

        :param fnames: optional iterable of field names to invalidate
        :param flush: whether pending updates should be flushed before invalidation.
            It is ``True`` by default, which ensures cache consistency.
            Do not use this parameter unless you know what you are doing.
        """
        if flush:
            self.flush_recordset(fnames)
        self._invalidate_cache(fnames, self._ids, flush=flush)
        if _orm_cache.isEnabledFor(logging.DEBUG):
            _orm_cache.debug(
                "invalidate_recordset %s: %d records, fnames=%s",
                self._name,
                len(self),
                fnames,
            )

    def _invalidate_cache(
        self,
        fnames: Collection[str] | None = None,
        ids: Sequence[IdType] | None = None,
        flush: bool = True,
    ) -> None:
        if (
            ids is not None and not ids
        ):  # Avoid invalidating field_inverses for no reason
            return

        fields: Collection[Field]
        if fnames is None:
            fields = self._fields.values()
        else:
            try:
                fields = [self._fields[fname] for fname in fnames]
            except KeyError as e:
                raise ValueError(
                    f"Invalid field {e.args[0]!r} on model {self._name!r}"
                ) from e

        env = self.env
        field_inverses = self.pool.field_inverses
        for field in fields:
            field._invalidate_cache(env, ids)
            # Also flush+invalidate inverse fields (e.g. the O2M inverse of a
            # M2O) to avoid stale reverse lookups.  With flush=False the caller
            # explicitly opted out of flushing, so only invalidate the inverse
            # caches.
            if inverses := field_inverses.get(field):
                for invf in inverses:
                    if flush:
                        env[invf.model_name].flush_model([invf.name])
                    invf._invalidate_cache(env)
