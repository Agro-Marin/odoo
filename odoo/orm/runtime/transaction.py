import logging
import typing
from contextlib import suppress
from weakref import WeakSet, WeakValueDictionary
from weakref import ref as weakref_ref

from odoo.libs.profiling import (
    NplusOneTracker,
    OrmProfiler,
    _n1_enabled,
    _orm_profiling_enabled,
)
from odoo.tools import OrderedSet, reset_cached_properties

from ..components.cache import FieldCache
from ..components.compute import ComputeEngine
from ..components.core import OrmCore
from ..components.unit_of_work import UnitOfWork
from .backend import POSTGRES_BACKEND, InMemoryBackend
from .recordset_cache import Cache
from .registry import Registry

if typing.TYPE_CHECKING:
    from ..fields.base import Field
    from .environment import Environment

_logger = logging.getLogger("odoo.api")

MAX_FIXPOINT_ITERATIONS = 1000


class _EnvironmentSet(WeakSet):
    __slots__ = ("_index",)

    def __init__(self) -> None:
        super().__init__()
        self.data = OrderedSet()
        self._index: WeakValueDictionary[tuple, Environment] = WeakValueDictionary()

    @staticmethod
    def key(uid: typing.Any, su: bool, context: typing.Any) -> tuple:
        return (uid, su, context)

    def add(self, env: Environment) -> None:
        super().add(env)
        self._index[self.key(env.uid, env.su, env.context)] = env

    def clear(self) -> None:
        super().clear()
        self._index.clear()

    def discard(self, env: Environment) -> None:
        super().discard(env)
        key = self.key(env.uid, env.su, env.context)
        if self._index.get(key) is env:
            del self._index[key]

    def lookup(self, key: tuple) -> Environment | None:
        env = self._index.get(key)
        return env if env is not None and env in self else None


class Transaction:
    __slots__ = (
        "_cache_store",
        "_compute_engine",
        "_last_env",
        "_n1_tracker",
        "_orm_profiler",
        "_ref_cache",
        "backend",
        "cache",
        "core",
        "default_env",
        "envs",
        "file_open_tmp_paths",
        "registry",
        "unit_of_work",
    )

    def __init__(self, registry: Registry, storage=None):
        self.registry = registry
        self.backend = (
            InMemoryBackend(storage) if storage is not None else POSTGRES_BACKEND
        )
        self.envs: _EnvironmentSet = _EnvironmentSet()
        self.default_env: Environment | None = None
        self._last_env: weakref_ref[Environment] | None = None

        self._cache_store: FieldCache[Field] = FieldCache(
            dirty_factory=OrderedSet, on_detach=self._drop_field_cache_memos
        )

        self._compute_engine: ComputeEngine[Field] = ComputeEngine(
            pending_factory=OrderedSet
        )

        self.core: OrmCore[Field] = OrmCore(
            cache=self._cache_store, engine=self._compute_engine
        )

        self.unit_of_work: UnitOfWork[Field] = UnitOfWork(
            self._cache_store,
            self._compute_engine,
            max_iterations=MAX_FIXPOINT_ITERATIONS,
        )
        self.unit_of_work.set_recompute_order(self._live_recompute_order)

        self.cache = Cache(self)
        self._ref_cache: dict[tuple[str, int], bool] = {}

        self._n1_tracker: NplusOneTracker | None = (
            NplusOneTracker() if _n1_enabled else None
        )

        self._orm_profiler: OrmProfiler | None = (
            OrmProfiler() if _orm_profiling_enabled else None
        )

        self.file_open_tmp_paths: list[str] = []

    def flush(self) -> None:
        if self.default_env is not None:
            self.default_env.flush_all()
        elif env := next(iter(self.envs), None):
            _logger.warning(
                "Transaction.flush(): no default_env; flushing as SUPERUSER"
            )
            from ..primitives import SUPERUSER_ID
            from .environment import Environment

            try:
                Environment(env.cr, SUPERUSER_ID, {}).flush_all()
            finally:
                self.default_env = None
        if self._n1_tracker is not None:
            self._n1_tracker.report()
            self._n1_tracker.clear()
        if self._orm_profiler is not None:
            self._orm_profiler.report()
            self._orm_profiler.clear()

    def _drop_field_cache_memos(self) -> None:
        for env in self.envs:
            with suppress(AttributeError):
                del env._field_cache_memo

    def clear(self):
        self._cache_store.clear()
        self._compute_engine.clear()
        self._ref_cache.clear()
        self._last_env = None
        if env := next(iter(self.envs), None):
            env.cr.cache.clear()

    def _live_recompute_order(self) -> dict[typing.Any, int]:
        registry = self.registry
        registry._ensure_field_triggers()
        return registry.model_graph.recompute_order

    def reset(self) -> None:
        self.registry = Registry(self.registry.db_name)
        for env in self.envs:
            reset_cached_properties(env)
        self.clear()

    def invalidate_field_data(self) -> None:
        self._cache_store.invalidate_all()
        self._ref_cache.clear()
