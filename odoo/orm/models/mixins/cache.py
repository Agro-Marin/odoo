import logging
import typing
from collections.abc import Collection, Mapping, Sequence

from ... import decorators as api
from ...helpers import resolve_fnames
from ._model_stubs import _ModelStubs

_orm_cache = logging.getLogger("odoo.orm.cache")

if typing.TYPE_CHECKING:
    from ..._typing import IdType
    from ...fields.base import Field


class RecordCache(Mapping):
    __slots__ = ["_record"]

    def __init__(self, record) -> None:
        if len(record) != 1:
            raise ValueError(f"Unexpected RecordCache({record})")
        self._record = record

    def _peek(self, field) -> Mapping | None:
        record = self._record
        env = record.env
        cache = env._core.get_field_data_or_none(field)
        if cache is None:
            return None
        if field in env._field_depends_context:
            return cache.get(env.cache_key(field))
        return cache

    def __contains__(self, name: object) -> bool:
        record = self._record
        field = record._fields.get(name)
        if field is None:
            return False
        cache = self._peek(field)
        return cache is not None and record.id in cache

    def __getitem__(self, name: str) -> object:
        record = self._record
        field = record._fields[name]
        cache = self._peek(field)
        if cache is None:
            raise KeyError(record.id)
        return cache[record.id]

    def __iter__(self) -> typing.Iterator[str]:
        record = self._record
        id_ = record.id
        env = record.env
        model_name = record._name
        depends_context = env._field_depends_context
        for field, cache in env._core.iter_field_items():
            if field.model_name != model_name:
                continue
            if field in depends_context:
                cache = cache.get(env.cache_key(field))
                if cache and id_ in cache:
                    yield field.name
            elif id_ in cache:
                yield field.name

    def __len__(self) -> int:
        return sum(1 for name in self)


class CacheMixin(_ModelStubs):
    __slots__ = ()

    @property
    def _cache(self) -> RecordCache:
        return RecordCache(self)

    @api.private
    def invalidate_model(
        self, fnames: Collection[str] | None = None, flush: bool = True
    ) -> None:
        if flush:
            self.flush_model(fnames)
        self._invalidate_cache(fnames, flush=flush)
        if _orm_cache.isEnabledFor(logging.DEBUG):
            _orm_cache.debug("invalidate_model %s: fnames=%s", self._name, fnames)

    @api.private
    def invalidate_recordset(
        self, fnames: Collection[str] | None = None, flush: bool = True
    ) -> None:
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
        if ids is not None and not ids:
            return

        fields: Collection[Field]
        if fnames is None:
            fields = self._fields.values()
        else:
            fields = resolve_fnames(self, fnames)

        env = self.env
        if not flush:
            self._check_no_pending_write(fields, ids)

        field_inverses = self.pool.field_inverses
        for field in fields:
            field._invalidate_cache(env, ids)
            if inverses := field_inverses.get(field):
                for invf in inverses:
                    if flush:
                        env[invf.model_name].flush_model([invf.name])
                    invf._invalidate_cache(env, keep_dirty=True)

    def _check_no_pending_write(
        self, fields: Collection[Field], ids: Sequence[IdType] | None
    ) -> None:
        found = self.env._core.find_pending_write(fields, ids)
        if found is None:
            return
        field, overlap = found
        raise ValueError(
            f"Refusing to invalidate {field} on records {overlap[:10]} with "
            f"flush=False: they hold a pending write that would be silently "
            f"lost.  Flush first (drop flush=False), restrict the records, "
            f"or discard the write explicitly."
        )
