"""Layer 1 facade — the id-level cache + compute surface (``env._core``).

:class:`OrmCore` composes :class:`FieldCache` and :class:`ComputeEngine` behind
a single flat object (``env._core``), the sanctioned handle for framework ORM
code to reach the cache and compute engine (ADR-0010). The two underlying
objects are private to :class:`~odoo.orm.runtime.transaction.Transaction`
(``_cache_store`` / ``_compute_engine``); code goes through this facade.

The facade is an **intentionally curated subset**, not a complete mirror: it
exposes field-value reads, dirty/patch tracking, recompute scheduling and field
protection — the operations the model layer drives by ``(field, id)``. It
deliberately does **not** expose cache *mutation* (``set_value``,
``invalidate_*``): those are Transaction's responsibility, and recordset-level
cache access belongs to the legacy ``env.cache`` wrapper. The one lifecycle
operation it does expose is :meth:`~OrmCore.clear_cache` — the intentional,
test-pinned rename of ``FieldCache.clear`` (data + dirty + patches only, never
compute state). Each exposed method carries the **same name** as
the ``FieldCache`` / ``ComputeEngine`` method it delegates to (a drift-guard
test enforces this); :meth:`OrmCore.new_scheduler` additionally hides
:class:`RecomputeScheduler` construction (and the raw ``engine.pending`` seed)
so model code drives a scheduler without reaching the engine directly.

Layer 1 of the three-layer ORM: Core (cache/compute/triggers — pure data, no
I/O); Layer 2 Persistence (SQL/cursors/fetch/write); Layer 3 API (ACL,
descriptors, translations). OrmCore has zero Odoo imports and is testable with
pure Python.
"""

from typing import TYPE_CHECKING, Any

from .cache import FieldCache
from .compute import ComputeEngine
from .recompute import RecomputeScheduler

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Iterator


class OrmCore:
    """Curated Layer 1 facade over FieldCache + ComputeEngine (see module docstring).

    Each pass-through method delegates to the identically-named method of the
    underlying ``FieldCache`` / ``ComputeEngine``; :meth:`new_scheduler` builds a
    recompute scheduler bound to the engine.
    """

    __slots__ = ("cache", "engine")

    def __init__(
        self,
        cache: FieldCache | None = None,
        engine: ComputeEngine | None = None,
    ) -> None:
        """Wrap a cache and compute engine, creating empty ones if omitted."""
        self.cache = cache if cache is not None else FieldCache()
        self.engine = engine if engine is not None else ComputeEngine()

    # Cache: data access

    def get_field_data(self, field: Any) -> dict[Any, Any]:
        """Return the live cache dict for *field* (``{id: value}``).

        Primary batch-access API: consumers that iterate records call this once,
        then loop with ``dict.get``.
        """
        return self.cache.get_field_data(field)

    def get_field_data_or_none(self, field: Any) -> dict[Any, Any] | None:
        """Return the cache dict for *field*, or ``None`` if nothing cached."""
        return self.cache.get_field_data_or_none(field)

    # Cache: dirty tracking

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

    # Cache: patches (x2many)

    def add_patch(self, field: Any, record_id: Any, new_id: Any) -> None:
        """Record a deferred x2many addition."""
        self.cache.add_patch(field, record_id, new_id)

    def get_patches(self, field: Any) -> dict[Any, list] | None:
        """Return the patches dict for *field*, or ``None``."""
        return self.cache.get_patches(field)

    # Cache: iteration

    def iter_field_items(self) -> Iterator[tuple[Any, dict[Any, Any]]]:
        """Iterate over ``(field, cache_dict)`` pairs."""
        return self.cache.iter_field_items()

    # Compute: scheduling

    def schedule(self, field: Any, ids: Iterable) -> None:
        """Mark *field* for recomputation on *ids*."""
        self.engine.schedule(field, ids)

    def new_scheduler(self, *, inline: bool = False) -> RecomputeScheduler:
        """Create a :class:`RecomputeScheduler` bound to this engine.

        The factory keeps scheduler construction (and the raw ``engine.pending``
        seed) behind the facade, so model code drives the returned scheduler
        without reaching ``core.engine`` directly.

        The scheduler's recursive-field prune (``marked``) is seeded from the
        engine's **live** pending map in both modes: ids already pending from
        earlier ``modified()`` calls in the same transaction are never
        re-traversed (each re-traversal costs inverse-resolution SQL in the
        trigger loop). Scheduling is idempotent, so the prune never loses a
        recomputation. The scheduler's ``to_recompute`` sets use the engine's
        own pending-set factory (``OrderedSet`` in a real transaction), so id
        order is preserved end-to-end into the pending map.

        :param inline: when ``True``, each processed entry's delta is scheduled
            into the engine's pending map immediately (``before=False``
            modification passes, where the lazy trigger-tree iterator must see
            newly pending fields while resolving inverse edges); when ``False``
            the caller drains ``to_recompute`` and batch-schedules.
        """
        return RecomputeScheduler(
            self.engine,
            marked=self.engine.pending,
            schedule_inline=inline,
            set_factory=self.engine.pending.default_factory,
        )

    def mark_done(self, field: Any, ids: Iterable) -> None:
        """Mark *field* as computed on *ids*."""
        self.engine.mark_done(field, ids)

    def is_pending(self, field: Any, record_id: Any) -> bool:
        """Check whether a specific *record_id* needs recomputation for *field*."""
        return self.engine.is_pending(field, record_id)

    def has_pending_field(self, field: Any) -> bool:
        """Return whether *field* has pending recomputations (hot-path guard)."""
        return self.engine.has_pending_field(field)

    def has_pending(self) -> bool:
        """Return whether any field has pending recomputations."""
        return self.engine.has_pending()

    def pending_ids(self, field: Any) -> set | tuple:
        """Return the set of pending record IDs for *field*."""
        return self.engine.pending_ids(field)

    def pending_fields(self) -> Collection[Any]:
        """Return a view of fields with pending recomputations."""
        return self.engine.pending_fields()

    def discard_field(self, field: Any) -> None:
        """Remove *field* from pending recomputations."""
        self.engine.discard_field(field)

    # Compute: protection

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

    # Lifecycle

    def clear_cache(self) -> None:
        """Clear only cache data + dirty + patches (not compute state)."""
        self.cache.clear()

    def __repr__(self) -> str:
        """Return a debug representation of the wrapped cache and engine."""
        return f"<OrmCore {self.cache!r} {self.engine!r}>"
