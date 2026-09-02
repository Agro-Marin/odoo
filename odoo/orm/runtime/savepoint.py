from __future__ import annotations

from typing import Protocol

from odoo.db.cursor import BaseCursor
from odoo.db.savepoint import _FlushingSavepoint
from odoo.tools import reset_cached_properties


class CacheInvalidating(Protocol):
    @property
    def cache_invalidated(self) -> set[str]: ...

    def clear_cache(self, *names: str) -> None: ...


class _OrmFlushingSavepoint(_FlushingSavepoint):
    __slots__ = ()

    _restores_orm_state = True

    def _restore_orm_state(self, cr: BaseCursor) -> None:
        txn = cr.transaction
        if txn is None:
            return
        self._reclear_invalidated_caches(txn.registry)
        current = type(txn.registry).registries.get(txn.registry.db_name)
        if current is not None and current is not txn.registry:
            txn.reset()
        else:
            txn.clear()
            for env in txn.envs:
                reset_cached_properties(env)

    @staticmethod
    def _reclear_invalidated_caches(registry: CacheInvalidating) -> None:
        if invalidated := tuple(registry.cache_invalidated):
            registry.clear_cache(*invalidated)


BaseCursor._flushing_savepoint_cls = _OrmFlushingSavepoint
