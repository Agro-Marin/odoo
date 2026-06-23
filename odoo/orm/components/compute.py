"""Standalone compute-scheduling engine for the ORM.

:class:`ComputeEngine` manages pending field recomputations and field protection
scopes. No dependency on Environment, BaseModel, or cursors — testable with pure
Python. It tracks:

* **Pending recomputations** — ``{field: set_of_record_ids}`` marking which
  stored-computed fields need recomputation on which records.
* **Field protection** — a stack of ``{field: frozenset_of_ids}`` scopes that
  suppress recomputation/invalidation during write operations.
"""

from collections import defaultdict
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Iterator


class _StackMap:
    """Minimal stack of mappings for field protection scopes.

    Standalone equivalent of ``odoo.libs.collections.misc.StackMap``; the Odoo
    import is avoided so the component stays pure-Python testable. Lookups search
    from top (most recent) to bottom; mutations affect the topmost mapping only.
    """

    __slots__ = ("_maps",)

    def __init__(self) -> None:
        self._maps: list[dict[Any, Any]] = []

    def get(self, key: Any, default: Any = None) -> Any:
        """Return the value for *key* searching from top to bottom."""
        for mapping in reversed(self._maps):
            try:
                return mapping[key]
            except KeyError:
                pass
        return default

    def __contains__(self, key: Any) -> bool:
        return any(key in m for m in self._maps)

    def __iter__(self) -> Iterator[Any]:
        return iter({key for m in self._maps for key in m})

    def pushmap(self, m: dict[Any, Any] | None = None) -> None:
        """Push a new mapping onto the stack."""
        self._maps.append(m if m is not None else {})

    def popmap(self) -> dict[Any, Any]:
        """Pop and return the topmost mapping."""
        return self._maps.pop()

    def __setitem__(self, key: Any, value: Any) -> None:
        self._maps[-1][key] = value

    def __getitem__(self, key: Any) -> Any:
        for mapping in reversed(self._maps):
            try:
                return mapping[key]
            except KeyError:
                pass
        raise KeyError(key)

    def __len__(self) -> int:
        """Return the number of mappings on the stack (scope depth).

        This is stack depth, *not* the count of distinct keys across scopes —
        use ``sum(1 for _ in self)`` for the latter.
        """
        return len(self._maps)


class ComputeEngine:
    """Manage pending recomputations and field protection.

    Operates on field keys and record IDs (any hashable). Internal structures:

    * ``_pending``: ``defaultdict(set_factory)`` — ``{field: mutable_set_of_ids}``
    * ``_protected``: ``_StackMap`` — ``{field: frozenset_of_ids}``

    ``_pending`` uses a configurable factory (default ``set``) so Transaction can
    pass ``OrderedSet`` for deterministic recomputation order.
    """

    __slots__ = ("_pending", "_protected")

    def __init__(self, pending_factory: type | None = None) -> None:
        self._pending: defaultdict[Any, set] = defaultdict(pending_factory or set)
        self._protected = _StackMap()

    # Raw data access

    @property
    def pending(self) -> defaultdict[Any, set]:
        """Return the raw pending dict ``{field: mutable_set_of_ids}``.

        For callers needing direct dict access — mainly
        :class:`RecomputeScheduler`, which reads it as the ``marked`` set for
        cycle detection when ``before=True``.
        """
        return self._pending

    # Scheduling

    def schedule(self, field: Any, ids: Iterable) -> None:
        """Mark *field* for recomputation on *ids*."""
        self._pending[field].update(ids)

    def mark_done(self, field: Any, ids: Iterable) -> None:
        """Mark *field* as computed on *ids*.

        Removes *ids* from the pending set; deletes the field entry if it
        becomes empty.
        """
        pending = self._pending.get(field)
        if pending is None:
            return
        pending.difference_update(ids)
        if not pending:
            del self._pending[field]

    def is_pending(self, field: Any, record_id: Any) -> bool:
        """Return whether *record_id* needs recomputation for *field*."""
        return record_id in self._pending.get(field, ())

    def pending_ids(self, field: Any) -> set | tuple:
        """Return the set of pending record IDs for *field* (may be empty)."""
        return self._pending.get(field, ())

    def pending_fields(self) -> Collection[Any]:
        """Return a view of fields with pending recomputations."""
        return self._pending.keys()

    def has_pending(self) -> bool:
        """Return whether any field has pending recomputations."""
        return bool(self._pending)

    def has_pending_field(self, field: Any) -> bool:
        """Return whether *field* has any pending recomputations.

        Cheaper than ``bool(pending_ids(field))`` — matters on the
        ``Field.__get__`` hot path, checked on every attribute access.
        """
        return field in self._pending

    def pending_real_fields(self) -> list[Any]:
        """Return fields with at least one real (truthy) pending record ID.

        Filters out fields with only NewIds (falsy) pending, since new records
        are not recomputed by the fixpoint loop.
        """
        return [field for field, ids in self._pending.items() if any(ids)]

    def discard_field(self, field: Any) -> None:
        """Remove *field* entirely from pending recomputations.

        No-op if not pending. Used when a field is deleted from the registry.
        """
        self._pending.pop(field, None)

    def prune_empty(self) -> None:
        """Remove fields with empty pending sets (called after recomputation)."""
        for field in [f for f in self._pending if not self._pending[f]]:
            del self._pending[field]

    # Protection

    def is_protected(self, field: Any, record_id: Any) -> bool:
        """Return whether *record_id* is protected for *field*."""
        return record_id in (self._protected.get(field) or ())

    def protected_ids(self, field: Any) -> frozenset:
        """Return the set of protected IDs for *field*."""
        return self._protected.get(field) or frozenset()

    def push_protection(self) -> None:
        """Push a new protection scope onto the stack."""
        self._protected.pushmap()

    def pop_protection(self) -> dict[Any, Any]:
        """Pop the most recent protection scope."""
        return self._protected.popmap()

    def protect(self, field: Any, ids: frozenset) -> None:
        """Protect *ids* for *field*, merging with existing protection in scope."""
        existing = self._protected.get(field)
        self._protected[field] = existing.union(ids) if existing else ids

    # Bulk operations

    def clear(self) -> None:
        """Clear all pending computations (protection is NOT cleared)."""
        self._pending.clear()

    def __repr__(self) -> str:
        n_fields = len(self._pending)
        n_entries = sum(len(ids) for ids in self._pending.values())
        n_scopes = len(self._protected)
        return f"<ComputeEngine pending={n_fields}f/{n_entries}e scopes={n_scopes}>"
