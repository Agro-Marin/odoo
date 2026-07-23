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

        :param max_iterations: safety backstop on the number of passes, for
            pathological cycles that evade the per-pass progress check (which
            aborts a genuine stall immediately).  A large value so that a
            long-but-converging compute/flush cascade is not misreported as a
            circular dependency.
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

    # Inspection

    def dirty_models(self) -> list[str]:
        """Return unique model names with dirty fields, in first-seen order."""
        # ``model_name`` is guaranteed by the FieldLike protocol (read directly,
        # like the sibling FieldCache.pop_dirty_for_model) — no getattr guard.
        seen: dict[str, None] = {}
        for fld in self.cache.iter_dirty_fields():
            if fld.model_name not in seen:
                seen[fld.model_name] = None
        return list(seen)

    # Convergence detection

    @staticmethod
    def _field_label(field: Any) -> str:
        """Human-readable ``model.field`` label for diagnostics/stall reports."""
        return f"{getattr(field, 'model_name', '?')}.{getattr(field, 'name', field)}"

    def recompute_snapshot(
        self, fields: list[Any] | None = None
    ) -> frozenset[tuple[Any, int]]:
        """Snapshot of ``(field, pending_count)`` for convergence detection.

        Includes only fields with at least one real (truthy) pending ID. Pass
        *fields* (a precomputed ``pending_real_fields()`` list) to avoid
        re-scanning the pending dict on the hot loop path.
        """
        if fields is None:
            fields = self.engine.pending_real_fields()
        return frozenset(
            (field, len(self.engine.pending_ids(field))) for field in fields
        )

    def check_convergence(
        self,
        prev_snapshot: frozenset[tuple[Any, int]] | None,
        curr_snapshot: frozenset[tuple[Any, int]],
    ) -> tuple[bool, list[str]]:
        """Check whether recomputation is making progress.

        :param prev_snapshot: previous result of :meth:`recompute_snapshot`.
        :param curr_snapshot: current result of :meth:`recompute_snapshot`.
        :return: ``(progressing, stalled_labels)`` — *progressing* is True if the
            snapshot changed (or *prev* was ``None``); *stalled_labels* lists
            field diagnostics when stalled.
        """
        if prev_snapshot is None or curr_snapshot != prev_snapshot:
            return True, []

        # Stalled — same fields with same counts
        stalled = sorted(f"{self._field_label(f)}({cnt})" for f, cnt in curr_snapshot)
        return False, stalled

    def check_flush_progress(
        self, prev_dirty_count: int, curr_dirty_count: int
    ) -> tuple[bool, list[str]]:
        """Check whether flushing is making progress.

        :return: ``(progressing, stalled_labels)``.
        """
        if curr_dirty_count < prev_dirty_count:
            return True, []

        stalled = sorted(self._field_label(f) for f in self.cache.iter_dirty_fields())
        return False, stalled

    # Convergence loops

    def run_recompute_loop(
        self,
        recompute_fn: Callable[[Any], None],
    ) -> LoopResult:
        """Execute the fixpoint recompute loop.

        Repeatedly collects fields with pending real recomputations and calls
        ``recompute_fn(field)`` for each, in dependency order when an order is
        available (see :meth:`set_recompute_order`) so a single pass resolves
        acyclic chains. Tracks monotonicity to detect stalls.

        :param recompute_fn: called as ``recompute_fn(field)``; expected to
            update the cache and call ``engine.mark_done()``.
        :return: :class:`LoopResult` with iteration count and convergence info.
            ``iterations`` follows the :class:`LoopResult` convention: passes
            that called ``recompute_fn`` count; the final empty pass does not.
        """
        result = LoopResult()
        # Resolve the order source once per loop. A callable (wired by
        # Transaction) reads the live registry order, surviving a registry
        # reload / metadata rebuild that invalidates field identities.
        order = self._recompute_order
        if callable(order):
            order = order()

        for iteration in range(self.max_iterations):
            fields = self.engine.pending_real_fields()
            if not fields:
                # This pass did no work — count only the prior working passes.
                result.iterations = iteration
                result.converged = True
                # Converged: discard any stall recorded on a prior iteration so
                # the result is not internally inconsistent (converged + stalled).
                result.stalled_fields = []
                break

            # No per-iteration progress snapshot: a count-based check
            # (``recompute_snapshot``/``check_convergence``) cannot tell a stall
            # from real progress when a pass computes a field on some records
            # while scheduling it on others (same field, same count, different
            # ids) — aborting there would drop computations.  ``max_iterations``
            # is a large backstop; a genuine cycle is caught there rather than
            # risk a false stall.  The helpers remain (unit-tested) for a future
            # id-level stall detector.

            # Sort by topological priority: dependencies (lower value) compute
            # first, so their results are cached when dependents run.
            if order:
                # Unknown fields sort last (max priority) — safe for dynamic ones.
                _max = len(order)
                fields.sort(key=lambda f: order.get(f, _max))

            for fld in fields:
                recompute_fn(fld)
        else:
            result.iterations = self.max_iterations
            pending = self.engine.pending_real_fields()
            result.converged = not pending
            if result.converged:
                # Discard any stall recorded on an earlier iteration: converging
                # exactly on the last iteration must not report stalled fields.
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

        :param recompute_fn: called as ``recompute_fn(field)`` for each field.
        :param flush_fn: called as ``flush_fn(model_names)`` with the models to
            flush.
        :return: :class:`LoopResult`.  ``iterations`` follows the
            :class:`LoopResult` convention: a pass counts when it recomputed
            or flushed anything (including a pass cut short by a recompute
            stall); a final pass that finds neither is not counted.
        """
        result = LoopResult()

        for iteration in range(self.max_iterations):
            # Inner recompute loop
            recompute_result = self.run_recompute_loop(recompute_fn)
            if not recompute_result.converged:
                # Computes must settle before flushing: break immediately on
                # recompute non-convergence.  This pass partially executed
                # (the inner loop ran recompute_fn), so it counts.
                result.iterations = iteration + 1
                result.converged = False
                result.stalled_fields = recompute_result.stalled_fields
                break

            # Collect dirty models
            model_names = self.dirty_models()
            if not model_names:
                # Nothing to flush: this pass counts only if its inner
                # recompute loop actually ran computations.
                result.iterations = iteration + (
                    1 if recompute_result.iterations else 0
                )
                result.converged = True
                # Converged: discard any stall recorded on a prior iteration so
                # the result is not internally inconsistent (converged + stalled).
                result.stalled_fields = []
                break

            # No per-iteration flush-progress snapshot (see run_recompute_loop):
            # a converging flush can re-dirty the same field on different records
            # via modified(), so a label/count-based check would false-stall.
            # ``max_iterations`` is the large backstop for a genuine flush cycle.

            # Flush all dirty models
            flush_fn(model_names)
        else:
            result.iterations = self.max_iterations
            # The final flush_fn can schedule new recomputations (via modified())
            # that have not yet produced dirty fields. Treating "no dirty models"
            # as converged would return success while those computes were never
            # run or persisted — silent data loss instead of a RuntimeError.
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
