"""Standalone field-value cache for the ORM.

:class:`FieldCache` manages cached field values, dirty tracking, and deferred
x2many patches. No dependency on Environment, BaseModel, or cursors — testable
with pure Python. Keyed by field objects (any hashable) and record IDs.
"""

import collections
from collections import defaultdict
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Iterator

# Sentinel for missing values — distinct from any real cached value (incl. None).
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
        self._data: defaultdict[Any, dict[Any, Any]] = defaultdict(dict)
        self._dirty: defaultdict[Any, set] = defaultdict(dirty_factory or set)
        self._patches: defaultdict[Any, defaultdict[Any, list]] = defaultdict(
            lambda: defaultdict(list)
        )

    # Data access

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
        try:
            return self._data[field][record_id]
        except KeyError:
            if default is _MISSING:
                raise
            return default

    def has_value(self, field: Any, record_id: Any) -> bool:
        """Return whether *record_id* has a cached value for *field*."""
        field_cache = self._data.get(field)
        return field_cache is not None and record_id in field_cache

    def insert_if_absent(self, field: Any, ids: Iterable, values: Iterable) -> None:
        """Set values only for IDs not already cached (bulk ``setdefault``).

        Preserves pending updates by not overwriting existing entries. The
        ``deque(maxlen=0)`` drains the ``map`` iterator in C (~15% faster than a
        Python loop). ``strict=True`` raises on length-mismatched iterables
        rather than truncating to the shorter side.
        """
        field_cache = self._data[field]
        collections.deque(
            map(field_cache.setdefault, ids, values, strict=True), maxlen=0
        )

    def update_batch(self, field: Any, ids: tuple, value: Any) -> None:
        """Set the same *value* for all *ids*.

        Optimized for the common singleton case (``len(ids) == 1``).
        """
        field_cache = self._data[field]
        if len(ids) <= 1:
            if ids:
                field_cache[ids[0]] = value
        else:
            field_cache.update(dict.fromkeys(ids, value))

    def pop_value(self, field: Any, record_id: Any, default: Any = _MISSING) -> Any:
        """Remove and return a cached value."""
        field_cache = self._data.get(field)
        if field_cache is None:
            if default is _MISSING:
                raise KeyError((field, record_id))
            return default
        if default is _MISSING:
            return field_cache.pop(record_id)
        return field_cache.pop(record_id, default)

    # Dirty tracking

    def mark_dirty(self, field: Any, ids: Iterable) -> None:
        """Mark *ids* as dirty for *field*."""
        self._dirty[field].update(ids)

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
                ids = self._dirty.pop(field)
                if ids:
                    result[field] = ids
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

    # Patches (deferred x2many additions)

    def add_patch(self, field: Any, record_id: Any, new_id: Any) -> None:
        """Record a deferred x2many addition."""
        self._patches[field][record_id].append(new_id)

    def get_patches(self, field: Any) -> dict[Any, list] | None:
        """Return the patches dict for *field*, or ``None``."""
        return self._patches.get(field)

    # Invalidation

    def invalidate_field(self, field: Any, ids: Collection | None = None) -> None:
        """Invalidate cached values for *field*.

        If *ids* is ``None``, clear the entire field cache.
        Otherwise, remove only the specified record IDs.
        """
        field_cache = self._data.get(field)
        if field_cache is None:
            return
        if ids is None:
            field_cache.clear()
        else:
            for id_ in ids:
                field_cache.pop(id_, None)

    def invalidate_all(self) -> None:
        """Clear all cached data except dirty entries.

        Dirty entries stay in ``_data`` so a subsequent flush can still read
        their values; non-dirty data is cleared to force re-fetch on next
        access. ``_dirty`` flags and ``_patches`` are never touched.
        """
        if not self._dirty:
            self._data.clear()
            return
        # Restrict each dirty field's sub-dict to its dirty IDs only.
        # Context-dependent fields (translate=True, company_dependent) keep
        # nested ``{cache_key: {id: value}}`` dicts; others keep flat
        # ``{id: value}``. Detect the shape by ``isinstance(k, tuple)``:
        # cache_keys are always tuples, record ids never are. Inspecting the
        # value instead would mis-classify dict-valued fields (Json, Properties)
        # and silently evict their dirty entries.
        for field in list(self._data):
            dirty_ids = self._dirty.get(field)
            if not dirty_ids:
                del self._data[field]
                continue
            field_cache = self._data[field]
            for k, v in list(field_cache.items()):
                if isinstance(k, tuple):
                    # context-dep shape: {cache_key: {id: value}}
                    for sub_id in list(v):
                        if sub_id not in dirty_ids:
                            del v[sub_id]
                    if not v:
                        del field_cache[k]
                elif k not in dirty_ids:
                    # flat shape: {id: value}
                    del field_cache[k]
            if not field_cache:
                del self._data[field]

    def clear(self) -> None:
        """Clear everything: data, dirty flags, and patches."""
        self._data.clear()
        self._dirty.clear()
        self._patches.clear()

    # Iteration & introspection

    def iter_fields(self) -> Iterator[Any]:
        """Iterate over fields that have cached data."""
        return iter(self._data)

    def iter_field_items(self) -> Iterator[tuple[Any, dict[Any, Any]]]:
        """Iterate over (field, field_cache_dict) pairs."""
        return iter(self._data.items())

    def has_field(self, field: Any) -> bool:
        """Return whether *field* has any cached data."""
        return field in self._data

    def __repr__(self) -> str:
        n_fields = len(self._data)
        n_dirty = sum(len(ids) for ids in self._dirty.values())
        return f"<FieldCache fields={n_fields} dirty_entries={n_dirty}>"
