"""Profiling and performance analysis infrastructure.

Framework-free profiling tools (no ``odoo.*`` imports). Includes generic
emitters (``Speedscope``, ``SourceMapGenerator``) and the ORM-shaped
instrumentation relocated here from ``tools/`` (ADR-0004): ``OrmProfiler`` and
the N+1 tracker are frame/thread samplers whose ORM-specificity is the external
configuration passed to them, not an ``odoo`` dependency, so they live with the
rest of the profiling infrastructure.
"""

from .nplusone import NplusOneTracker, _n1_enabled
from .orm_profiler import OrmProfiler, _OrmProfile, _orm_profiling_enabled
from .speedscope import Speedscope
from .sourcemap_generator import SourceMapGenerator

__all__ = [
    "NplusOneTracker",
    "OrmProfiler",
    "SourceMapGenerator",
    "Speedscope",
    "_OrmProfile",
    "_n1_enabled",
    "_orm_profiling_enabled",
]
