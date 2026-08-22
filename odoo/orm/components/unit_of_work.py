from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from ._protocols import FieldKey
    from .cache import FieldCache
    from .compute import ComputeEngine

STALL_REPEATS = 16

SNAPSHOT_AFTER = 3


@dataclass(slots=True)
class LoopResult:
    iterations: int = 0
    converged: bool = True
    stalled_fields: list[str] = field(default_factory=list)


class UnitOfWork[F: FieldKey = FieldKey]:
    __slots__ = ("_recompute_order", "cache", "engine", "max_iterations")

    def __init__(
        self,
        cache: FieldCache[F],
        engine: ComputeEngine[F],
        max_iterations: int = 1000,
    ) -> None:
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
        self._recompute_order = order

    def dirty_models(self) -> list[str]:
        seen: dict[str, None] = {}
        for fld in self.cache.iter_dirty_fields():
            model_name = getattr(fld, "model_name", None)
            if model_name is not None and model_name not in seen:
                seen[model_name] = None
        return list(seen)

    def _pending_snapshot(self) -> dict[Any, frozenset]:
        return {
            fld: frozenset(self.engine.pending_ids(fld))
            for fld in self.engine.pending_fields()
        }

    def _dirty_snapshot(self) -> dict[Any, frozenset]:
        return {
            fld: frozenset(self.cache.get_dirty(fld) or ())
            for fld in self.cache.iter_dirty_fields()
        }

    @staticmethod
    def _field_label(field: F) -> str:
        return f"{getattr(field, 'model_name', '?')}.{getattr(field, 'name', field)}"

    def run_recompute_loop(
        self,
        recompute_fn: Callable[[F], None],
    ) -> LoopResult:
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
        recompute_fn: Callable[[F], None],
        flush_fn: Callable[[list[str]], None],
    ) -> LoopResult:
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
        n_dirty = self.cache.dirty_entry_count()
        n_pending = sum(
            len(self.engine.pending_ids(f)) for f in self.engine.pending_fields()
        )
        return f"<UnitOfWork dirty={n_dirty} pending={n_pending} max_iter={self.max_iterations}>"
