"""Layer 1 facade — unified cache + compute operations.

:class:`OrmCore` composes :class:`FieldCache` and :class:`ComputeEngine`
behind a single flat API, eliminating the multi-attribute traversal chains
that internal ORM consumers currently navigate::

    # Before (3 attr lookups + method):
    env.transaction.compute_engine.has_pending_field(field)
    env.transaction.cache_store.get_field_data(field)

    # After (1 attr lookup + method):
    env._core.has_pending(field)
    env._core.field_data(field)

This is the **Layer 1** of the three-layer ORM architecture:

- Layer 1 (Core): cache, compute, triggers — pure data, no I/O
- Layer 2 (Persistence): SQL, cursors, fetch, write — DB ops
- Layer 3 (API): ACL, descriptors, translations — user-facing

OrmCore has **zero Odoo imports** and is fully testable with pure Python.
"""

from typing import TYPE_CHECKING, Any

from .cache import FieldCache
from .compute import ComputeEngine

if TYPE_CHECKING:
    from collections import defaultdict
    from collections.abc import Collection, Iterable, Iterator


class OrmCore:
    """Unified Layer 1 facade over FieldCache + ComputeEngine.

    Designed as a single-object entry point that internal ORM code
    (``_read_format``, ``mapped``, ``filtered``, ``sorted``, ``modified``,
    ``flush_model``, ``_make_scalar_get``) accesses via ``env._core``.

    All methods delegate to the **public** APIs of the underlying
    :class:`FieldCache` / :class:`ComputeEngine`, so component-level invariants
    are never bypassed (the facade owns no data of its own).  Several of those
    public methods (e.g. :meth:`ComputeEngine.has_pending_field`) are already
    written for the hot path, so delegation is the intended use, not a tax.

    Usage::

        core = OrmCore()
        core.set_value(field, record_id, value)
        core.mark_dirty(field, [record_id])
        core.schedule(field, [record_id])

        # Hot-path cache resolve: pending check + dict get
        value = core.resolve(field, record_id)

        # Batch cache access: return the raw dict
        field_cache = core.field_data(field)
    """

    __slots__ = ("cache", "engine")

    def __init__(
        self,
        cache: FieldCache | None = None,
        engine: ComputeEngine | None = None,
    ) -> None:
        self.cache = cache if cache is not None else FieldCache()
        self.engine = engine if engine is not None else ComputeEngine()

    # ------------------------------------------------------------------
    # Cache: data access
    # ------------------------------------------------------------------

    def field_data(self, field: Any) -> dict[Any, Any]:
        """Return the live cache dict for *field* (``{id: value}``).

        This is the primary batch-access API.  Internal consumers that
        iterate over records (``_read_format``, ``mapped``, ``sorted``)
        call this once, then loop with ``dict.get``.

        Replaces: ``env.transaction.cache_store.get_field_data(field)``
        """
        return self.cache.get_field_data(field)

    def field_data_or_none(self, field: Any) -> dict[Any, Any] | None:
        """Return the cache dict for *field*, or ``None`` if nothing cached."""
        return self.cache.get_field_data_or_none(field)

    def get_value(self, field: Any, record_id: Any, default: Any = None) -> Any:
        """Return a single cached value, or *default*.

        Note the deliberate contract difference from :meth:`FieldCache.get_value`,
        which *raises* ``KeyError`` on a miss by default: this facade returns
        *default* (``None``) instead — a convenience for hot-path callers that do
        not distinguish "absent" from "cached ``None``".  Pass an explicit
        *default* to control the miss behavior of either.
        """
        field_cache = self.cache.get_field_data_or_none(field)
        if field_cache is None:
            return default
        return field_cache.get(record_id, default)

    def set_value(self, field: Any, record_id: Any, value: Any) -> None:
        """Set a single cached value."""
        self.cache.set_value(field, record_id, value)

    def insert_if_absent(self, field: Any, ids: Iterable, values: Iterable) -> None:
        """Set values only for IDs not already cached (``setdefault`` in bulk)."""
        self.cache.insert_if_absent(field, ids, values)

    def update_batch(self, field: Any, ids: tuple, value: Any) -> None:
        """Set the same *value* for all *ids*."""
        self.cache.update_batch(field, ids, value)

    def pop_value(self, field: Any, record_id: Any, default: Any = None) -> Any:
        """Remove and return a cached value."""
        return self.cache.pop_value(field, record_id, default)

    # ------------------------------------------------------------------
    # Cache: dirty tracking
    # ------------------------------------------------------------------

    def mark_dirty(self, field: Any, ids: Iterable) -> None:
        """Mark *ids* as dirty for *field*."""
        self.cache.mark_dirty(field, ids)

    def get_dirty(self, field: Any) -> set | None:
        """Return the dirty IDs for *field*, or ``None``."""
        return self.cache.get_dirty(field)

    def pop_dirty(self, field: Any) -> set | None:
        """Remove and return the dirty IDs for *field*."""
        return self.cache.pop_dirty(field)

    def pop_dirty_for_model(self, model_name: str) -> dict[Any, set]:
        """Pop all dirty fields belonging to *model_name*."""
        return self.cache.pop_dirty_for_model(model_name)

    def has_dirty_field(self, field: Any) -> bool:
        """Return whether *field* has any dirty entries."""
        return self.cache.has_dirty_field(field)

    def is_any_dirty(self) -> bool:
        """Return whether any field has dirty entries."""
        return self.cache.is_any_dirty()

    def iter_dirty_fields(self) -> Iterator[Any]:
        """Iterate over fields that have dirty entries."""
        return self.cache.iter_dirty_fields()

    # ------------------------------------------------------------------
    # Cache: patches (x2many)
    # ------------------------------------------------------------------

    def add_patch(self, field: Any, record_id: Any, new_id: Any) -> None:
        """Record a deferred x2many addition."""
        self.cache.add_patch(field, record_id, new_id)

    def get_patches(self, field: Any) -> dict[Any, list] | None:
        """Return the patches dict for *field*, or ``None``."""
        return self.cache.get_patches(field)

    # ------------------------------------------------------------------
    # Cache: invalidation
    # ------------------------------------------------------------------

    def invalidate_field(self, field: Any, ids: Collection | None = None) -> None:
        """Invalidate cached values for *field*."""
        self.cache.invalidate_field(field, ids)

    def invalidate_all(self) -> None:
        """Clear all cached data (but not dirty or patches)."""
        self.cache.invalidate_all()

    # ------------------------------------------------------------------
    # Cache: iteration
    # ------------------------------------------------------------------

    def iter_fields(self) -> Iterator[Any]:
        """Iterate over fields with cached data."""
        return self.cache.iter_fields()

    def iter_field_items(self) -> Iterator[tuple[Any, dict[Any, Any]]]:
        """Iterate over ``(field, cache_dict)`` pairs."""
        return self.cache.iter_field_items()

    def has_field(self, field: Any) -> bool:
        """Return whether *field* has cached data."""
        return self.cache.has_field(field)

    # ------------------------------------------------------------------
    # Compute: scheduling
    # ------------------------------------------------------------------

    def schedule(self, field: Any, ids: Iterable) -> None:
        """Mark *field* for recomputation on *ids*."""
        self.engine.schedule(field, ids)

    def mark_done(self, field: Any, ids: Iterable) -> None:
        """Mark *field* as computed on *ids*."""
        self.engine.mark_done(field, ids)

    def is_pending(self, field: Any, record_id: Any) -> bool:
        """Check whether a specific *record_id* needs recomputation for *field*."""
        return self.engine.is_pending(field, record_id)

    def has_pending(self, field: Any) -> bool:
        """Fast check: does *field* have pending recomputations?

        This is the hot-path guard in ``_make_scalar_get`` and
        ``ensure_computed`` — it delegates to
        :meth:`ComputeEngine.has_pending_field`, which is itself a single
        ``__contains__`` on the pending dict and documented as hot-path code.
        """
        return self.engine.has_pending_field(field)

    def has_any_pending(self) -> bool:
        """Return whether any field has pending recomputations."""
        return self.engine.has_pending()

    def pending_ids(self, field: Any) -> set | tuple:
        """Return the set of pending record IDs for *field*."""
        return self.engine.pending_ids(field)

    def pending_fields(self) -> Collection[Any]:
        """Return a view of fields with pending recomputations."""
        return self.engine.pending_fields()

    @property
    def pending(self) -> defaultdict[Any, set]:
        """Raw pending dict — for RecomputeScheduler cycle detection."""
        return self.engine.pending

    def pending_real_fields(self) -> list[Any]:
        """Fields with at least one real (truthy) pending record ID."""
        return self.engine.pending_real_fields()

    def discard_field(self, field: Any) -> None:
        """Remove *field* from pending recomputations."""
        self.engine.discard_field(field)

    # ------------------------------------------------------------------
    # Compute: protection
    # ------------------------------------------------------------------

    def is_protected(self, field: Any, record_id: Any) -> bool:
        """Return whether *record_id* is protected for *field*."""
        return self.engine.is_protected(field, record_id)

    def protected_ids(self, field: Any) -> frozenset:
        """Return the set of protected IDs for *field*."""
        return self.engine.protected_ids(field)

    def push_protection(self) -> None:
        """Push a new protection scope."""
        self.engine.push_protection()

    def pop_protection(self) -> dict[Any, Any]:
        """Pop the most recent protection scope."""
        return self.engine.pop_protection()

    def protect(self, field: Any, ids: frozenset) -> None:
        """Protect *ids* for *field* in the current scope."""
        self.engine.protect(field, ids)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Clear all cached data, dirty flags, patches, and pending computations."""
        self.cache.clear()
        self.engine.clear()

    def clear_cache(self) -> None:
        """Clear only cache data + dirty + patches (not compute state)."""
        self.cache.clear()

    def clear_compute(self) -> None:
        """Clear only pending computations (not cache)."""
        self.engine.clear()

    def __repr__(self) -> str:
        return f"<OrmCore {self.cache!r} {self.engine!r}>"
