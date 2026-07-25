"""Standalone recomputation scheduler for the ORM.

:class:`RecomputeScheduler` converts trigger-traversal results into scheduling
decisions. No dependency on Environment, BaseModel, or cursors — testable with
pure Python. It processes (field, ids) trigger entries (from the trigger tree
traversal in ``RecomputeMixin._modified_triggers``) and for each routes to:

* **Recomputation** (stored-computed fields) — accumulated in :attr:`to_recompute`
* **Cache invalidation** (non-stored computed) — accumulated in :attr:`to_invalidate`
* **Recursive traversal** (recursive fields) — returned from :meth:`process_entry`

Protection subtraction and cycle detection are handled internally via the
:class:`ComputeEngine`.
"""

from __future__ import annotations

import typing
from collections import defaultdict
from typing import Any

if typing.TYPE_CHECKING:
    from collections.abc import Container, Mapping
    from collections.abc import Set as AbstractSet

    from ._protocols import SchedulableField
    from .compute import ComputeEngine


class RecomputeScheduler:
    """Route trigger entries into recomputation scheduling decisions.

    Pure-data processor over field-like keys (hashables with ``recursive`` and
    ``is_stored_computed`` attributes) and ID sets. Accumulates results across
    :meth:`process_entry` calls so the caller can interleave trigger traversal
    (DB-coupled) with scheduling (pure logic).

    :param compute_engine: standalone compute engine for protection checks.
    :param marked: read-only ``{field: set_of_ids}`` of fields already pending,
        for pruning recursive stored-computed fields. Pass the engine's *live*
        pending map (``engine.pending``) so ids already scheduled by earlier
        ``modified()`` calls in the same transaction are not re-traversed
        (each re-traversal costs inverse-resolution SQL in the caller);
        scheduling is idempotent, so the prune is always safe.
    :param schedule_inline: when ``True``, each entry's routed recompute ids
        (the per-entry delta, after protection and cycle filtering) are
        scheduled into the engine's pending map immediately, so a lazy
        trigger-tree iterator sees newly pending fields mid-traversal.
    :param set_factory: set-like factory for the :attr:`to_recompute` id sets
        (e.g. ``OrderedSet`` for deterministic recompute order); defaults to
        ``set``.
    """

    __slots__ = (
        "_engine",
        "_inline",
        "_marked",
        "_seen_recursive",
        "to_invalidate",
        "to_recompute",
    )

    def __init__(
        self,
        compute_engine: ComputeEngine,
        marked: Mapping | None = None,
        *,
        schedule_inline: bool = False,
        set_factory: type | None = None,
    ) -> None:
        """Bind to *compute_engine* and start with empty result accumulators."""
        self._engine = compute_engine
        self._marked: Mapping = marked if marked is not None else {}
        self._inline = schedule_inline
        self._seen_recursive: dict[Any, set] = defaultdict(set)
        self.to_recompute: dict[Any, set] = defaultdict(set_factory or set)
        self.to_invalidate: list[tuple[Any, frozenset]] = []

    def process_entry(
        self,
        field: SchedulableField,
        ids: AbstractSet,
        cached_ids: Container | None = None,
    ) -> frozenset:
        """Process one trigger entry.

        Applies protection subtraction and cycle detection, then routes the
        entry to :attr:`to_recompute` or :attr:`to_invalidate`.

        :param field: a :class:`~._protocols.SchedulableField` (reads
            ``.recursive`` and ``.is_stored_computed``).
        :param ids: record IDs affected by the modification.
        :param cached_ids: for recursive non-stored fields, the IDs with cached
            data; only those are processed. ``None`` skips this filter.
        :returns: frozenset of IDs needing recursive traversal (empty if none).
            The caller resolves inverse dependencies for these (DB-coupled) and
            feeds the resulting entries back in.
        """
        protected = self._engine.protected_ids(field)
        if protected:
            ids = ids - protected
        if not ids:
            return frozenset()

        recursive_ids: frozenset = frozenset()
        if field.recursive:
            if field.is_stored_computed:
                m = self._marked.get(field)
                if m:
                    ids = ids - m
                r = self.to_recompute.get(field)
                if r and ids:
                    ids = ids - r
            else:
                seen = self._seen_recursive.get(field)
                if seen:
                    ids = ids - seen
                if cached_ids is not None and ids:
                    ids = type(ids)(id_ for id_ in ids if id_ in cached_ids)
            if not ids:
                return frozenset()
            if not field.is_stored_computed:
                self._seen_recursive[field].update(ids)
            recursive_ids = frozenset(ids)

        if field.is_stored_computed:
            self.to_recompute[field].update(ids)
            if self._inline:
                self._engine.schedule(field, ids)
        else:
            self.to_invalidate.append((field, frozenset(ids)))

        return recursive_ids

    def __repr__(self) -> str:
        """Return a debug summary with recompute/invalidate field and entry counts."""
        n_recompute = sum(len(ids) for ids in self.to_recompute.values())
        n_invalidate = sum(len(ids) for _, ids in self.to_invalidate)
        return (
            f"<RecomputeScheduler "
            f"recompute={len(self.to_recompute)}f/{n_recompute}e "
            f"invalidate={len(self.to_invalidate)}f/{n_invalidate}e>"
        )
