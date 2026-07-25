"""Standalone field-value cache for the ORM.

:class:`FieldCache` manages cached field values, dirty tracking, and deferred
x2many patches. No dependency on Environment, BaseModel, or cursors — testable
with pure Python. Keyed by field objects (any hashable) and record IDs.
"""

from collections import ChainMap, defaultdict
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Iterator, Mapping

_MISSING = object()


class FieldCache:
    """Standalone cache for field values, keyed by field objects and record IDs.

    Internal data structures:

    * ``_data``: ``{field: {record_id: value}}`` — cached values.
    * ``_dirty``: ``{field: set_of_ids}`` — ids whose cached value differs from DB.
    * ``_patches``: ``{field: {record_id: [ids_to_add]}}`` — deferred x2many adds.

    All three are ``defaultdict`` so first access auto-creates the sub-collection.
    """

    __slots__ = ("_data", "_dirty", "_patches")

    def __init__(self, dirty_factory: type | None = None) -> None:
        """Initialize empty data, dirty, and patch maps.

        :param dirty_factory: set-like factory for the dirty-id sets (e.g.
            ``OrderedSet`` for deterministic flush order); defaults to ``set``.
        """
        self._data: defaultdict[Any, dict[Any, Any]] = defaultdict(dict)
        self._dirty: defaultdict[Any, set] = defaultdict(dirty_factory or set)
        self._patches: defaultdict[Any, defaultdict[Any, list]] = defaultdict(
            lambda: defaultdict(list)
        )

    def get_field_data(self, field: Any) -> dict[Any, Any]:
        """Return the cache dict for *field*, creating it if needed.

        The returned dict is the *live* dict — mutations are visible to the cache.
        """
        return self._data[field]

    def get_field_data_or_none(self, field: Any) -> dict[Any, Any] | None:
        """Return the cache dict for *field*, or ``None`` if nothing is cached."""
        return self._data.get(field)

    def set_value(self, field: Any, record_id: Any, value: Any) -> None:
        """Set a single cached value."""
        self._data[field][record_id] = value

    def get_value(self, field: Any, record_id: Any, default: Any = _MISSING) -> Any:
        """Return the cached value, or *default* if not present.

        Raises ``KeyError`` if *default* is not provided and the value is missing.
        """
        field_cache = self._data.get(field)
        if field_cache is not None:
            try:
                return field_cache[record_id]
            except KeyError:
                pass
        if default is _MISSING:
            raise KeyError(record_id)
        return default

    def has_value(self, field: Any, record_id: Any) -> bool:
        """Return whether *record_id* has a cached value for *field*."""
        field_cache = self._data.get(field)
        return field_cache is not None and record_id in field_cache

    def mark_dirty(self, field: Any, ids: Iterable) -> None:
        """Mark *ids* as dirty for *field*.

        Empty *ids* is a no-op and never creates an entry (see the ``_dirty``
        invariant). Callers routinely pass a generator that filters out NewIds
        (e.g. ``(id_ for id_ in ids if id_)``), which is empty for all-new
        records — that must not register a phantom dirty field.
        """
        existing = self._dirty.get(field)
        if existing is None:
            ids = list(ids)
            if not ids:
                return
            existing = self._dirty[field]
        existing.update(ids)

    def get_dirty(self, field: Any) -> set | None:
        """Return the set of dirty IDs for *field*, or ``None``."""
        return self._dirty.get(field)

    def pop_dirty(self, field: Any) -> set | None:
        """Remove and return the set of dirty IDs for *field*."""
        return self._dirty.pop(field, None)

    def pop_dirty_for_model(self, model_name: str) -> dict[Any, set]:
        """Pop all dirty fields belonging to *model_name*.

        Iterates the (usually small) dirty dict, so O(n_dirty_global) rather
        than O(n_model_fields).
        """
        result: dict[Any, set] = {}
        for field in list(self._dirty):
            if field.model_name == model_name:
                result[field] = self._dirty.pop(field)
        return result

    def is_any_dirty(self) -> bool:
        """Return whether any field has dirty entries."""
        return bool(self._dirty)

    def has_dirty_field(self, field: Any) -> bool:
        """Return whether *field* has any dirty entries."""
        return bool(self._dirty.get(field))

    def iter_dirty_fields(self) -> Iterator[Any]:
        """Iterate over fields that have dirty entries."""
        return iter(self._dirty)

    def dirty_entry_count(self) -> int:
        """Return the total number of dirty (field, record_id) entries."""
        return sum(len(ids) for ids in self._dirty.values())

    def add_patch(self, field: Any, record_id: Any, new_id: Any) -> None:
        """Record a deferred x2many addition."""
        self._patches[field][record_id].append(new_id)

    def get_patches(self, field: Any) -> dict[Any, list] | None:
        """Return the patches dict for *field*, or ``None``."""
        return self._patches.get(field)

    def invalidate(
        self,
        field: Any,
        ids: Collection | None = None,
        *,
        context_dependent: bool,
    ) -> None:
        """Invalidate cached values for *field* (all if *ids* is ``None``)."""
        field_cache = self._data.get(field)
        if not field_cache:
            return
        if not context_dependent:
            if ids is None:
                field_cache.clear()
            else:
                for id_ in ids:
                    field_cache.pop(id_, None)
            return
        if ids is None:
            for key in list(field_cache):
                if isinstance(key, tuple):
                    field_cache[key].clear()
                else:
                    del field_cache[key]
            return
        for id_ in ids:
            field_cache.pop(id_, None)
        for key, sub_cache in field_cache.items():
            if isinstance(key, tuple):
                for id_ in ids:
                    sub_cache.pop(id_, None)

    def all_cached_ids(
        self, field: Any, *, context_dependent: bool
    ) -> Mapping[Any, Any]:
        """Return a read-only mapping view of every record id cached for *field*.

        The shape bit comes from the caller (``Field._is_context_dependent``),
        like :meth:`invalidate`. Flat fields return the live cache dict;
        context-dependent fields return a ``ChainMap`` over the per-context
        sub-dicts (tuple keys only — stale flat entries from the module-setup
        window are ignored, as before the mixed-state decode was unified).
        Callers must not mutate the result.
        """
        field_cache = self._data.get(field)
        if not field_cache:
            return {}
        if context_dependent:
            subs = [v for k, v in field_cache.items() if isinstance(k, tuple)]
            return ChainMap(*subs) if subs else {}
        return field_cache

    def invalidate_field(self, field: Any, ids: Collection | None = None) -> None:
        """Invalidate cached values for *field*, probing the cache shape.

        Compatibility wrapper for callers that do not know the shape bit
        (standalone tests, benchmarks — production code knows the shape and
        calls :meth:`invalidate` directly): probes for a tuple key (O(n) on
        flat caches) and delegates. It additionally drops emptied per-context
        sub-dicts — safe only here, where no ``env._field_cache_memo`` aliases
        them (see :meth:`invalidate`).
        """
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

    def invalidate_all(self) -> None:
        """Clear all cached data except dirty entries.

        Dirty entries stay in ``_data`` so a subsequent flush can still read
        their values; non-dirty data is cleared to force re-fetch on next
        access. ``_dirty`` flags and ``_patches`` are never touched.
        """
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
        """Clear everything: data, dirty flags, and patches."""
        self._data.clear()
        self._dirty.clear()
        self._patches.clear()

    def iter_field_items(self) -> Iterator[tuple[Any, dict[Any, Any]]]:
        """Iterate over (field, field_cache_dict) pairs."""
        return iter(self._data.items())

    def __repr__(self) -> str:
        """Return a debug summary with field and dirty-entry counts."""
        n_fields = len(self._data)
        n_dirty = sum(len(ids) for ids in self._dirty.values())
        return f"<FieldCache fields={n_fields} dirty_entries={n_dirty}>"
