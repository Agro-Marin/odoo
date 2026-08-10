from collections import ChainMap, defaultdict
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from ._protocols import FieldKey

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterable, Mapping

_MISSING = object()


class FieldCache[F: FieldKey = FieldKey]:
    __slots__ = ("_data", "_dirty", "_on_detach", "_patches")

    def __init__(
        self,
        dirty_factory: type | None = None,
        on_detach: Callable[[], None] | None = None,
    ) -> None:
        self._data: defaultdict[F, dict[Any, Any]] = defaultdict(dict)
        self._dirty: defaultdict[F, set[Any]] = defaultdict(dirty_factory or set)
        self._patches: defaultdict[F, defaultdict[Any, list[Any]]] = defaultdict(
            lambda: defaultdict(list)
        )
        self._on_detach = on_detach

    def get_field_data(self, field: F) -> dict[Any, Any]:
        return self._data[field]

    def get_field_data_or_none(self, field: F) -> dict[Any, Any] | None:
        return self._data.get(field)

    def set_value(self, field: F, record_id: Any, value: Any) -> None:
        self._data[field][record_id] = value

    def get_value(self, field: F, record_id: Any, default: Any = _MISSING) -> Any:
        field_cache = self._data.get(field)
        if field_cache is not None:
            try:
                return field_cache[record_id]
            except KeyError:
                pass
        if default is _MISSING:
            raise KeyError(record_id)
        return default

    def has_value(self, field: F, record_id: Any) -> bool:
        field_cache = self._data.get(field)
        return field_cache is not None and record_id in field_cache

    def mark_dirty(self, field: F, ids: Iterable[Any]) -> None:
        existing = self._dirty.get(field)
        if existing is None:
            ids = list(ids)
            if not ids:
                return
            existing = self._dirty[field]
        existing.update(ids)

    def get_dirty(self, field: F) -> set[Any] | None:
        return self._dirty.get(field)

    def pop_dirty(self, field: F) -> set[Any] | None:
        return self._dirty.pop(field, None)

    def pop_dirty_for_model(self, model_name: str) -> dict[F, set[Any]]:
        result: dict[Any, set] = {}
        for field in list(self._dirty):
            if getattr(field, "model_name", None) == model_name:
                result[field] = self._dirty.pop(field)
        return result

    def is_any_dirty(self) -> bool:
        return bool(self._dirty)

    def has_dirty_field(self, field: F) -> bool:
        return bool(self._dirty.get(field))

    def iter_dirty_fields(self) -> Iterator[F]:
        return iter(self._dirty)

    def dirty_entry_count(self) -> int:
        return sum(len(ids) for ids in self._dirty.values())

    def add_patch(self, field: F, record_id: Any, new_id: Any) -> None:
        self._patches[field][record_id].append(new_id)

    def get_patches(self, field: F) -> dict[Any, list[Any]] | None:
        return self._patches.get(field)

    def invalidate(
        self,
        field: F,
        ids: Iterable[Any] | None = None,
        *,
        context_dependent: bool,
        keep_dirty: bool = False,
    ) -> None:
        field_cache = self._data.get(field)
        if not field_cache:
            return
        dirty = (self._dirty.get(field) or None) if keep_dirty else None
        if not context_dependent:
            if ids is None:
                if dirty is None:
                    field_cache.clear()
                else:
                    for id_ in [k for k in field_cache if k not in dirty]:
                        del field_cache[id_]
            else:
                for id_ in ids:
                    if dirty is None or id_ not in dirty:
                        field_cache.pop(id_, None)
            return
        if ids is None:
            for key in list(field_cache):
                if isinstance(key, tuple):
                    sub_cache = field_cache[key]
                    if dirty is None:
                        sub_cache.clear()
                    else:
                        for id_ in [k for k in sub_cache if k not in dirty]:
                            del sub_cache[id_]
                elif dirty is None or key not in dirty:
                    del field_cache[key]
            return
        if isinstance(ids, Iterator):
            ids = tuple(ids)
        if dirty is not None:
            ids = [id_ for id_ in ids if id_ not in dirty]
        for id_ in ids:
            field_cache.pop(id_, None)
        for key, sub_cache in field_cache.items():
            if isinstance(key, tuple):
                for id_ in ids:
                    sub_cache.pop(id_, None)

    def all_cached_ids(self, field: F, *, context_dependent: bool) -> Mapping[Any, Any]:
        field_cache = self._data.get(field)
        if not field_cache:
            return {}
        if context_dependent:
            subs = [v for k, v in field_cache.items() if isinstance(k, tuple)]
            return ChainMap(*subs) if subs else {}
        return field_cache

    def iter_context_caches(self, field: F) -> Iterator[tuple[tuple, dict]]:
        field_cache = self._data.get(field)
        if not field_cache:
            return
        for key, sub_cache in field_cache.items():
            if isinstance(key, tuple):
                yield key, sub_cache

    def invalidate_field(self, field: F, ids: Collection | None = None) -> None:
        field_cache = self._data.get(field)
        if field_cache is None:
            return
        if ids is None:
            field_cache.clear()
            return
        context_dependent = any(isinstance(key, tuple) for key in field_cache)
        self.invalidate(field, ids, context_dependent=context_dependent)
        if context_dependent:
            emptied = [
                key
                for key, sub_cache in field_cache.items()
                if isinstance(key, tuple) and not sub_cache
            ]
            for key in emptied:
                del field_cache[key]
            if emptied and self._on_detach is not None:
                self._on_detach()

    def invalidate_all(self) -> None:
        if self._on_detach is not None:
            self._on_detach()
        if not self._dirty:
            self._data.clear()
            return
        for field in list(self._data):
            dirty_ids = self._dirty.get(field)
            if not dirty_ids:
                del self._data[field]
                continue
            field_cache = self._data[field]
            for k, v in list(field_cache.items()):
                if isinstance(k, tuple):
                    for sub_id in list(v):
                        if sub_id not in dirty_ids:
                            del v[sub_id]
                    if not v:
                        del field_cache[k]
                elif k not in dirty_ids:
                    del field_cache[k]
            if not field_cache:
                del self._data[field]

    def clear(self) -> None:
        if self._on_detach is not None:
            self._on_detach()
        self._data.clear()
        self._dirty.clear()
        self._patches.clear()

    def iter_field_items(self) -> Iterator[tuple[F, dict[Any, Any]]]:
        return iter(self._data.items())

    def __repr__(self) -> str:
        n_fields = len(self._data)
        n_dirty = sum(len(ids) for ids in self._dirty.values())
        return f"<FieldCache fields={n_fields} dirty_entries={n_dirty}>"
