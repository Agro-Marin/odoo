from typing import Protocol

from .nplusone import NplusOneTracker, _n1_enabled
from .orm_profiler import OrmProfiler, _OrmProfile, _orm_profiling_enabled
from .speedscope import Speedscope
from .sourcemap_generator import SourceMapGenerator

__all__ = [
    "NplusOneTracker",
    "OrmObserver",
    "OrmProfiler",
    "SourceMapGenerator",
    "Speedscope",
    "_OrmProfile",
    "_n1_enabled",
    "_orm_profiling_enabled",
    "enabled_observers",
]


class OrmObserver(Protocol):
    def on_operation(
        self,
        operation: str,
        model_name: str,
        record_count: int,
        fields: frozenset[str],
    ) -> None: ...

    def on_operation_done(
        self,
        operation: str,
        model_name: str,
        record_count: int,
        elapsed: float,
    ) -> None: ...

    def report(self) -> None: ...

    def clear(self) -> None: ...


def enabled_observers() -> tuple[OrmObserver, ...]:
    observers: list[OrmObserver] = []
    if _n1_enabled:
        observers.append(NplusOneTracker())
    if _orm_profiling_enabled:
        observers.append(OrmProfiler())
    return tuple(observers)
