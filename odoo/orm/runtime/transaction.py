"""ORM Transaction — per-cursor state container.

A :class:`Transaction` owns the cache, compute engine, :class:`OrmCore` facade,
:class:`UnitOfWork`, and profiling tools for a single cursor's lifetime.  Created
lazily on the first ``Environment.__new__`` for a cursor with no transaction yet.
"""

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
    """The transaction's live environments, plus an index for O(1) lookup.

    ``Environment.__new__`` reuses an existing environment for the same
    ``(uid, su, context)``.  Scanning this set to find it is O(live
    environments) on every ``with_context`` / ``sudo`` / ``with_company``,
    which is 2.5 us at one environment and 143 us at a thousand, so the lookup
    is indexed instead.

    The index lives *inside* the collection because the set is mutated from
    outside the ORM: ``odoo.tests.common`` clears it on cleanup and re-adds
    only the environments that predate the test, deliberately retiring the
    ones a test created.  A parallel index would keep serving those, and their
    ``user`` / ``company`` / ``companies`` cached properties are stale -- which
    surfaced as record rules filtering on the wrong company.  :meth:`lookup`
    additionally confirms membership, so a mutator that bypasses :meth:`add`
    (``remove``, ``difference_update``, ...) can only cost a rebuilt
    environment, never hand back a retired one.
    """

    __slots__ = ("_index",)

    def __init__(self) -> None:
        super().__init__()
        self.data = OrderedSet()
        self._index: WeakValueDictionary[tuple, Environment] = WeakValueDictionary()

    @staticmethod
    def key(uid: typing.Any, su: bool, context: typing.Any) -> tuple:
        """Return the index key identifying an environment."""
        return (uid, su, context)

    def add(self, env: Environment) -> None:
        super().add(env)
        self._index[self.key(env.uid, env.su, env.context)] = env

    def clear(self) -> None:
        super().clear()
        self._index.clear()

    def discard(self, env: Environment) -> None:
        super().discard(env)
        # Only evict the index entry if it still points at *this* environment:
        # the key is ``(uid, su, context)``, so a rebuilt environment with the
        # same parameters shares it, and popping blindly would retire the live
        # one along with the discarded duplicate.
        key = self.key(env.uid, env.su, env.context)
        if self._index.get(key) is env:
            del self._index[key]

    def lookup(self, key: tuple) -> Environment | None:
        """Return the live environment registered under *key*, if any."""
        env = self._index.get(key)
        return env if env is not None and env in self else None


class Transaction:
    """An object holding ORM data structures for a transaction."""

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
        "storage",
        "unit_of_work",
    )

    def __init__(self, registry: Registry, storage=None):
        self.registry = registry
        self.storage = storage
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
        """Flush pending computations and updates in the transaction."""
        if self.default_env is not None:
            self.default_env.flush_all()
        elif env := next(iter(self.envs), None):
            _logger.warning(
                "Transaction.flush(): no default_env; flushing as SUPERUSER"
            )
            from ..primitives import SUPERUSER_ID
            from .environment import Environment

            Environment(env.cr, SUPERUSER_ID, {}).flush_all()
        if self._n1_tracker is not None:
            self._n1_tracker.report()
            self._n1_tracker.clear()
        if self._orm_profiler is not None:
            self._orm_profiler.report()
            self._orm_profiler.clear()

    def _drop_field_cache_memos(self) -> None:
        """Purge every environment's ``Field._get_cache`` memo.

        Wired into :class:`FieldCache` as its ``on_detach`` callback, so it runs
        automatically whenever the cache removes a per-field dict rather than
        emptying it in place.  The memos alias those dicts and the
        ``Field.__get__`` fast paths read them without revalidating, so leaving
        one behind serves stale values and swallows writes.
        """
        for env in self.envs:
            with suppress(AttributeError):
                del env._field_cache_memo

    def clear(self):
        """Clear the caches and pending computations/updates."""
        self._cache_store.clear()
        self._compute_engine.clear()
        self._ref_cache.clear()
        self._last_env = None
        if env := next(iter(self.envs), None):
            env.cr.cache.clear()

    def _live_recompute_order(self) -> dict[typing.Any, int] | None:
        """Return the current registry's recompute order, or None.

        Bound into :class:`UnitOfWork` as a live source so the flush loop always
        reads ``self.registry``'s order, surviving a :meth:`reset` registry swap
        or metadata rebuild (which invalidate the field identities a snapshot
        would be keyed on).
        """
        registry = self.registry
        if registry is None:
            return None
        registry._ensure_field_triggers()
        model_graph = getattr(registry, "model_graph", None)
        return model_graph.recompute_order if model_graph is not None else None

    def reset(self) -> None:
        """Clear the transaction and reassign the registry on all its envs.

        Recommended after reloading the registry.  The :class:`UnitOfWork`
        recompute order needs no re-wiring: :meth:`_live_recompute_order` reads
        ``self.registry`` lazily and picks up the new registry below.
        """
        self.registry = Registry(self.registry.db_name)
        for env in self.envs:
            reset_cached_properties(env)
        self.clear()

    def invalidate_field_data(self) -> None:
        """Invalidate the cache of all fields.

        Unsafe: invalidating a dirty field drops the value to be written.

        The per-environment ``_field_cache_memo`` purge is not done here: the
        cache fires :meth:`_drop_field_cache_memos` itself (see
        :meth:`FieldCache.__init__`).
        """
        self._cache_store.invalidate_all()
        self._ref_cache.clear()
