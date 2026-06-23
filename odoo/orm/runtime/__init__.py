"""Runtime infrastructure for the ORM.

- :class:`Environment`: request-scoped context (user, cursor, metadata).
- :class:`Transaction`: per-cursor cache + recomputation state.
- :class:`Registry`: per-database model registry.
- :class:`Cache`: backward-compat wrapper over the transaction cache.
"""

from .cache_compat import Cache, Starred
from .environment import Environment
from .registry import (
    _CACHES_BY_KEY,
    _REGISTRY_CACHES,
    DummyRLock,
    Registry,
    TriggerTree,
)
from .transaction import MAX_FIXPOINT_ITERATIONS, Transaction

# Registers the ORM-aware flushing savepoint as
# BaseCursor._flushing_savepoint_cls so cr.savepoint(flush=True) restores ORM
# cache/env state on rollback.  Last, so BaseCursor and Transaction are imported.
from . import savepoint as _savepoint

__all__ = [
    "MAX_FIXPOINT_ITERATIONS",
    "_CACHES_BY_KEY",
    "_REGISTRY_CACHES",
    "Cache",
    "DummyRLock",
    # Environment
    "Environment",
    # Registry
    "Registry",
    "Starred",
    "Transaction",
    "TriggerTree",
]
