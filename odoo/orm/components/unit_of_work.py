"""Standalone flush scheduling engine for the ORM.

:class:`UnitOfWork` encapsulates the fixpoint convergence loop and dirty-tracking
scans used when flushing. It has no dependency on Environment, BaseModel, or
cursors: recomputation and SQL flushing are injected via callbacks.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from .cache import FieldCache
    from .compute import ComputeEngine

STALL_REPEATS = 16
"""Consecutive no-change passes before a loop is declared stalled.

Above 1 so that a ``recompute_fn`` making progress the pending map cannot
express (see :meth:`UnitOfWork.run_recompute_loop`) is not cut short, far below
``max_iterations`` so a genuine cycle fails in seconds instead of grinding
through a thousand full passes.
"""

SNAPSHOT_AFTER = 3
"""Passes a loop may run before it starts snapshotting for the stall detector.

A snapshot is ``{field: frozenset(ids)}`` over everything pending (and dirty),
so it costs one frozenset per field and is O(total entries) — negligible next to
a pass that recomputes and writes them, but *not* negligible when the loop
converges in one or two passes and the snapshot is the only extra work.  A
``create()`` of a thousand records measured 3.6% slower with it taken
unconditionally.  Real flushes converge in a handful of passes; only a loop that
is already failing to converge reaches this threshold and starts paying.
"""


@dataclass(slots=True)
class LoopResult:
    """Outcome of a convergence loop: iterations, converged flag, stalled fields.

    ``iterations`` counts the passes that performed any work — i.e. invoked
    the injected ``recompute_fn`` / ``flush_fn`` at least once, fully or
    partially (a pass aborted mid-way by a stall still counts). A final pass
    that finds nothing pending/dirty and merely detects convergence is *not*
    counted; when the loop exhausts its budget, ``iterations`` equals
    ``max_iterations``. Both loops apply this convention.
    """

    iterations: int = 0
    converged: bool = True
    stalled_fields: list[str] = field(default_factory=list)


class UnitOfWork:
    """Flush scheduling engine: convergence detection + ordering.

    Owns dirty-field scanning, flush ordering, and stall/progress detection.
    SQL execution and recomputation dispatch are injected via callbacks.
    """

    __slots__ = ("_recompute_order", "cache", "engine", "max_iterations")

    def __init__(
        self,
        cache: FieldCache,
        engine: ComputeEngine,
        max_iterations: int = 1000,
    ) -> None:
        """Bind to *cache* and *engine* with a convergence iteration cap.

        :param max_iterations: the hard bound on non-draining (cyclic) state:
            both loops stop when nothing is pending/dirty, when the
            :data:`STALL_REPEATS` stall detector fires, or when this many
            passes have run.  A large value so that a long-but-converging
            compute/flush cascade is not misreported as a circular dependency;
            the stall detector is what keeps a genuine cycle from paying it.
        """
        self.cache = cache
        self.engine = engine
        self.max_iterations = max_iterations
        self._recompute_order: (
            dict[Any, int] | Callable[[], dict[Any, int] | None] | None
        ) = None

    def set_recompute_order(
        self,
        order: dict[Any, int] | Callable[[], dict[Any, int] | None] | None,
    ) -> None:
        """Set the topological recompute order from ModelGraph.

        :param order: a ``{field: priority}`` mapping (lower = compute first), or
            a zero-arg callable returning such a mapping (or ``None``). Prefer the
            callable when the order can change mid-transaction (registry reload,
            metadata rebuild): the order is keyed by field identity, so a one-time
            snapshot stops matching the rebuilt ``Field`` objects and degrades to
            insertion order. A callable is re-resolved each
            :meth:`run_recompute_loop`; a plain mapping is captured as-is.
        """
        self._recompute_order = order

    def dirty_models(self) -> list[str]:
        """Return unique model names with dirty fields, in first-seen order."""
        seen: dict[str, None] = {}
        for fld in self.cache.iter_dirty_fields():
            if fld.model_name not in seen:
                seen[fld.model_name] = None
        return list(seen)

    def _pending_snapshot(self) -> dict[Any, frozenset]:
        """Return ``{field: frozenset(pending_ids)}`` for the whole engine."""
        return {
            fld: frozenset(self.engine.pending_ids(fld))
            for fld in self.engine.pending_fields()
        }

    def _dirty_snapshot(self) -> dict[Any, frozenset]:
        """Return ``{field: frozenset(dirty_ids)}`` for the whole cache."""
        return {
            fld: frozenset(self.cache.get_dirty(fld) or ())
            for fld in self.cache.iter_dirty_fields()
        }

    @staticmethod
    def _field_label(field: Any) -> str:
        """Human-readable ``model.field`` label for diagnostics/stall reports."""
        return f"{getattr(field, 'model_name', '?')}.{getattr(field, 'name', field)}"

    def run_recompute_loop(
        self,
        recompute_fn: Callable[[Any], None],
    ) -> LoopResult:
        """Execute the fixpoint recompute loop.

        Repeatedly collects fields with pending real recomputations and calls
        ``recompute_fn(field)`` for each, in dependency order when an order is
        available (see :meth:`set_recompute_order`) so a single pass resolves
        acyclic chains.

        Terminates when nothing real is pending, at the ``max_iterations`` cap,
        or when :data:`STALL_REPEATS` consecutive passes have left the pending
        map byte-identical (the stall detector).

        A *count* of pending entries cannot detect a stall — a cycle can trade
        one entry for another and keep the count level, and a converging cascade
        can legitimately grow it — but a repeated ``{field: frozenset(ids)}``
        snapshot can: a ``recompute_fn`` that is a function of the pending map
        will keep producing the same output from the same input.  That premise
        is the caller's, not this component's (an injected callback is free to
        make progress this map cannot see), which is why the detector needs
        several repeats rather than one, and why ``max_iterations`` stays the
        hard bound.  Its value: without it a circular ``@api.depends`` does not
        fail, it grinds through ``max_iterations`` full recompute passes first,
        each one issuing the cascade's SQL over the whole recordset.

        :param recompute_fn: called as ``recompute_fn(field)``; expected to
            update the cache and call ``engine.mark_done()``.
        :return: :class:`LoopResult` with iteration count and convergence info.
            ``iterations`` follows the :class:`LoopResult` convention: passes
            that called ``recompute_fn`` count; neither the final empty pass nor
            the pass that only observes the stall does.
        """
        result = LoopResult()
        order = self._recompute_order
        if callable(order):
            order = order()

        previous: dict[Any, frozenset] | None = None
        repeats = 0
        for iteration in range(self.max_iterations):
            fields = self.engine.pending_real_fields()
            if not fields:
                result.iterations = iteration
                result.converged = True
                result.stalled_fields = []
                break

            if iteration >= SNAPSHOT_AFTER:
                snapshot = self._pending_snapshot()
                repeats = repeats + 1 if snapshot == previous else 0
                if repeats >= STALL_REPEATS:
                    result.iterations = iteration
                    result.converged = False
                    result.stalled_fields = sorted(
                        self._field_label(f) for f in snapshot
                    )
                    break
                previous = snapshot

            if order:
                _max = len(order)
                fields.sort(key=lambda f: order.get(f, _max))

            for fld in fields:
                recompute_fn(fld)
        else:
            result.iterations = self.max_iterations
            pending = self.engine.pending_real_fields()
            result.converged = not pending
            if result.converged:
                result.stalled_fields = []
            else:
                result.stalled_fields = sorted(self._field_label(f) for f in pending)

        return result

    def run_flush_loop(
        self,
        recompute_fn: Callable[[Any], None],
        flush_fn: Callable[[list[str]], None],
    ) -> LoopResult:
        """Execute the outer flush loop: recompute → flush → repeat.

        Each flush may trigger new computations (via ``modified()``), dirtying
        more fields and requiring another iteration.

        Like :meth:`run_recompute_loop`, :data:`STALL_REPEATS` consecutive
        passes that leave the combined (dirty, pending) state identical are a
        stall: the next pass would repeat them verbatim.

        :param recompute_fn: called as ``recompute_fn(field)`` for each field.
        :param flush_fn: called as ``flush_fn(model_names)`` with the models to
            flush.
        :return: :class:`LoopResult`.  ``iterations`` follows the
            :class:`LoopResult` convention: a pass counts when it recomputed
            or flushed anything (including a pass cut short by a recompute
            stall); a final pass that finds neither is not counted.
        """
        result = LoopResult()

        previous: tuple[dict[Any, frozenset], dict[Any, frozenset]] | None = None
        repeats = 0
        for iteration in range(self.max_iterations):
            recompute_result = self.run_recompute_loop(recompute_fn)
            if not recompute_result.converged:
                result.iterations = iteration + 1
                result.converged = False
                result.stalled_fields = recompute_result.stalled_fields
                break

            model_names = self.dirty_models()
            if not model_names:
                result.iterations = iteration + (
                    1 if recompute_result.iterations else 0
                )
                result.converged = True
                result.stalled_fields = []
                break

            if iteration >= SNAPSHOT_AFTER:
                snapshot = (self._dirty_snapshot(), self._pending_snapshot())
                repeats = repeats + 1 if snapshot == previous else 0
                if repeats >= STALL_REPEATS:
                    result.iterations = iteration
                    result.converged = False
                    result.stalled_fields = sorted(
                        {self._field_label(f) for f in snapshot[0]}
                        | {self._field_label(f) for f in snapshot[1]}
                    )
                    break
                previous = snapshot

            flush_fn(model_names)
        else:
            result.iterations = self.max_iterations
            dirty_models = self.dirty_models()
            pending = self.engine.pending_real_fields()
            result.converged = not dirty_models and not pending
            if result.converged:
                result.stalled_fields = []
            else:
                labels = {self._field_label(f) for f in self.cache.iter_dirty_fields()}
                labels.update(self._field_label(f) for f in pending)
                result.stalled_fields = sorted(labels)

        return result

    def __repr__(self) -> str:
        """Return a debug summary with dirty and pending entry counts."""
        n_dirty = self.cache.dirty_entry_count()
        n_pending = sum(
            len(self.engine.pending_ids(f)) for f in self.engine.pending_fields()
        )
        return f"<UnitOfWork dirty={n_dirty} pending={n_pending} max_iter={self.max_iterations}>"
