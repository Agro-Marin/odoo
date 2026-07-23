"""ORM Transaction — per-cursor state container.

A :class:`Transaction` owns the cache, compute engine, :class:`OrmCore` facade,
:class:`UnitOfWork`, and profiling tools for a single cursor's lifetime.  Created
lazily on the first ``Environment.__new__`` for a cursor with no transaction yet.
"""

import logging
import typing
from contextlib import suppress
from weakref import WeakSet
from weakref import ref as weakref_ref

from odoo.tools import OrderedSet, reset_cached_properties
from odoo.tools.nplusone import NplusOneTracker, _n1_enabled
from odoo.tools.orm_profiler import OrmProfiler, _orm_profiling_enabled

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

# Safety backstop on flush/recompute passes.  This cap is the ONLY termination
# guarantee for non-draining state: the UnitOfWork loops stop when nothing is
# pending/dirty or when the cap is hit — there is no per-pass stall detection
# (a count-based snapshot cannot tell a stall from progress when a pass
# recomputes a field on some records while re-scheduling it on others; see
# UnitOfWork.run_recompute_loop).  Large so a long-but-converging cascade of
# computes that write other fields is not misreported as a circular dependency;
# a genuine cycle burns the cap and is then reported as non-converged.
MAX_FIXPOINT_ITERATIONS = 1000


class Transaction:
    """An object holding ORM data structures for a transaction."""

    __slots__ = (
        "_Transaction__file_open_tmp_paths",
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
        "registry",
        "storage",
        "unit_of_work",
    )

    def __init__(self, registry: Registry, storage=None):
        self.registry = registry
        # Optional in-memory storage backend (DictBackend): when set, CRUD
        # dispatches to ``backend`` instead of generating SQL.  ``None`` = the
        # PostgreSQL fast path (no backend object, no dispatch indirection).
        self.storage = storage
        self.backend = InMemoryBackend(storage) if storage is not None else None
        self.envs: WeakSet[Environment] = WeakSet()
        self.envs.data = OrderedSet()  # type: ignore[attr-defined]
        # default environment (for flushing)
        self.default_env: Environment | None = None
        # MRU env-lookup cache (repeated with_user/sudo).  Weakref so it does not
        # prolong env lifetime; callers do ``_last_env() if _last_env else None``.
        self._last_env: weakref_ref[Environment] | None = None

        # OrderedSet dirty factory preserves write order during flush.
        self._cache_store = FieldCache(dirty_factory=OrderedSet)

        # OrderedSet pending factory gives deterministic recompute order.
        self._compute_engine = ComputeEngine(pending_factory=OrderedSet)

        # Layer 1 facade (env._core).
        self.core = OrmCore(cache=self._cache_store, engine=self._compute_engine)

        self.unit_of_work = UnitOfWork(
            self._cache_store,
            self._compute_engine,
            max_iterations=MAX_FIXPOINT_ITERATIONS,
        )
        # Process pending fields in dependency order (fewer convergence
        # iterations).  A callable, not a snapshot, so the order tracks reset()
        # registry swaps and metadata rebuilds — both make new Field identities
        # that a snapshot keyed on field identity would stop matching.
        self.unit_of_work.set_recompute_order(self._live_recompute_order)

        # backward-compatible view of the cache
        self.cache = Cache(self)
        # env.ref() exists() results, keyed by (model_name, record_id)
        self._ref_cache: dict[tuple[str, int], bool] = {}

        # N+1 CRUD detection (None when disabled, zero overhead)
        self._n1_tracker: NplusOneTracker | None = (
            NplusOneTracker() if _n1_enabled else None
        )

        # Aggregate ORM profiler (None when disabled, zero overhead)
        self._orm_profiler: OrmProfiler | None = (
            OrmProfiler() if _orm_profiling_enabled else None
        )

        # temporary directories (see odoo.tools.file_open_temporary_directory)
        self.__file_open_tmp_paths = []  # type: ignore[misc, var-annotated] # noqa: PLE0237

    def flush(self) -> None:
        """Flush pending computations and updates in the transaction."""
        if self.default_env is not None:
            self.default_env.flush_all()
        elif env := next(iter(self.envs), None):
            # No default_env (every env had uid==0).  Flush as SUPERUSER, not
            # public_user (which often lacks write access → AccessError); the
            # dirty records bypassed ACL anyway, else default_env would be set.
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

    def clear(self):
        """Clear the caches and pending computations/updates."""
        self._cache_store.clear()  # data + dirty + patches
        self._compute_engine.clear()  # pending recomputations
        self._ref_cache.clear()
        # reset per-env Field._get_cache() memos
        for env in self.envs:
            with suppress(AttributeError):
                del env._field_cache_memo
        self._last_env = None
        # all envs of the transaction share the same cursor
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
        # Route through the ``_field_triggers`` guard, like every other
        # model_graph consumer, so this never reads a mid-rebuild graph: it
        # ensures the trigger map (and thus ``recompute_order``) is fully built
        # and published before the read.
        registry._field_triggers  # noqa: B018
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
        """
        self._cache_store.invalidate_all()
        self._ref_cache.clear()
        # reset Field._get_cache()
        for env in self.envs:
            with suppress(AttributeError):
                del env._field_cache_memo
