"""Runtime infrastructure for the ORM.

- :class:`Environment`: request-scoped context (user, cursor, metadata).
- :class:`Transaction`: per-cursor cache + recomputation state.
- :class:`Registry`: per-database model registry.
- :class:`Cache`: backward-compat wrapper over the transaction cache.
"""

from ..components.model_graph import TriggerTree
from .cache_compat import Cache
from .environment import Environment
from .registry import (
    _CACHES_BY_KEY,
    _REGISTRY_CACHES,
    DummyRLock,
    Registry,
)
from .transaction import MAX_FIXPOINT_ITERATIONS, Transaction

from . import savepoint as _savepoint

__all__ = [
    "MAX_FIXPOINT_ITERATIONS",
    "_CACHES_BY_KEY",
    "_REGISTRY_CACHES",
    "Cache",
    "DummyRLock",
    "Environment",
    "Registry",
    "Transaction",
    "TriggerTree",
]
