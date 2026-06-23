"""Runtime infrastructure package for the ORM.

This package contains classes for ORM runtime management:
- Environment: Request-scoped context with user, database cursor, and metadata
- Transaction: Database transaction context with caching and recomputation
- Registry: Per-database model registry
- Cache: Record cache for the transaction (backward-compat wrapper)

Package Structure:
- environment.py: Environment class
- transaction.py: Transaction class, MAX_FIXPOINT_ITERATIONS
- cache_compat.py: Cache (backward-compat wrapper), Starred helper
- registry.py: Registry, DummyRLock classes

Usage:
    from odoo.orm.runtime import Environment, Registry, Transaction

    # Get environment
    env = Environment(cr, uid, context)

    # Access registry
    registry = Registry(db_name)

Note: This package was renamed from ``odoo.orm.context`` in Odoo 19.0.
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

# Importing this registers the ORM-aware flushing savepoint as
# BaseCursor._flushing_savepoint_cls (see odoo.orm.runtime.savepoint), so
# cr.savepoint(flush=True) restores ORM cache/env state on rollback once the
# ORM is loaded.  Kept last so BaseCursor and Transaction are already imported.
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
