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
from .backend import InMemoryBackend
from .cache_compat import Cache
from .registry import Registry

if typing.TYPE_CHECKING:
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
        # `storage` is consumed here and not retained.  It used to be kept as
        # `self.storage`, which was the channel six CRUD mixins sniffed to ask
        # "am I on the test backend?"; ADR-0011 replaced those sniffs with the
        # `env.backend` port and left the attribute behind.  Nothing has read it
        # since -- verified across odoo/, enterprise/ and agromarin/ -- so it is
        # gone; `backend` is the whole of what callers need.
        self.backend = InMemoryBackend(storage) if storage is not None else None
        self.envs: _EnvironmentSet = _EnvironmentSet()
        self.default_env: Environment | None = None
        self._last_env: weakref_ref[Environment] | None = None

        self._cache_store = FieldCache(
            dirty_factory=OrderedSet, on_detach=self._drop_field_cache_memos
        )

        self._compute_engine = ComputeEngine(pending_factory=OrderedSet)

        self.core = OrmCore(cache=self._cache_store, engine=self._compute_engine)

        self.unit_of_work = UnitOfWork(
            self._cache_store,
            self._compute_engine,
            max_iterations=MAX_FIXPOINT_ITERATIONS,
        )
        self.unit_of_work.set_recompute_order(self._live_recompute_order)

        self.cache = Cache(self)
        self._ref_cache: dict[tuple[str, int], bool] = {}
        """``{(model, id): True}`` for xml-ids :meth:`Environment.ref` proved to
        exist, saving it one ``exists()`` query per lookup (1.1 us cached vs
        59.6 us, one query each).

        Sound only because a positive cannot go stale within a transaction:
        cursors run at ``REPEATABLE READ``, so a delete committed elsewhere is
        invisible here, and an ORM ``unlink()`` clears this map through
        :meth:`invalidate_field_data`.  Deleting rows with raw SQL and then
        calling ``ref()`` on them returns a browse of the dead id instead of
        raising -- invalidate after such a delete, as with any other cache."""

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

            # Environment.__new__ installs itself as `transaction.default_env`
            # when there is none and `uid` is a truthy int -- and SUPERUSER_ID
            # is 1. So building this fallback used to make it the default_env,
            # which meant the warning above fired EXACTLY ONCE per transaction
            # and every later flush silently took the branch above, still as
            # superuser, with no log at all.
            #
            # Restore default_env afterwards so the fallback stays a fallback:
            # the warning then fires on every flush that needs it, which is the
            # only way anyone finds out this is happening.
            #
            # Unconditionally, because this branch is only reachable when
            # `default_env` is None -- the `if` above tested `is not None`.  The
            # guard used to read `previous_default = self.default_env` and
            # restore only `if previous_default is None`, a condition that
            # cannot be false here.
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

    def _live_recompute_order(self) -> dict[typing.Any, int] | None:
        registry = self.registry
        if registry is None:
            return None
        registry._ensure_field_triggers()
        model_graph = getattr(registry, "model_graph", None)
        return model_graph.recompute_order if model_graph is not None else None

    def reset(self) -> None:
        self.registry = Registry(self.registry.db_name)
        for env in self.envs:
            reset_cached_properties(env)
        self.clear()

    def invalidate_field_data(self) -> None:
        self._cache_store.invalidate_all()
        self._ref_cache.clear()
