from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from odoo.db.cursor import BaseCursor
from odoo.db.savepoint import Savepoint, _FlushingSavepoint
from odoo.libs.debug_log import DebugLog
from odoo.tools import reset_cached_properties

_debug = DebugLog(__name__)


class CacheInvalidating(Protocol):
    @property
    def cache_invalidation_generation(self) -> dict[str, int]: ...

    def clear_cache(self, *names: str) -> None: ...


def _note_rows_vanished(cr: BaseCursor) -> None:
    if cr.transaction is not None:
        cr.transaction.core.note_rows_vanished()


class _OrmSavepoint(Savepoint):
    __slots__ = ()

    if TYPE_CHECKING:
        _cr: BaseCursor

    def rollback(self) -> None:
        super().rollback()
        _note_rows_vanished(self._cr)


class _OrmFlushingSavepoint(_FlushingSavepoint):
    __slots__ = ("_generation_before",)

    _restores_orm_state = True

    def _save_orm_state(self, cr: BaseCursor) -> None:
        txn = cr.transaction
        self._generation_before = (
            {} if txn is None else dict(txn.registry.cache_invalidation_generation)
        )

    def _restore_orm_state(self, cr: BaseCursor) -> None:
        txn = cr.transaction
        if txn is None:
            return
        txn.core.note_rows_vanished()
        self._clear_invalidated_caches(txn.registry, self._generation_before)
        current = type(txn.registry).registries.get(txn.registry.db_name)
        _debug.logic(
            "savepoint.restore_orm_state",
            db=txn.registry.db_name,
            registry_replaced=current is not None and current is not txn.registry,
            envs=len(txn.envs),
        )
        if current is not None and current is not txn.registry:
            txn.reset()
        else:
            txn.clear()
            for env in txn.envs:
                reset_cached_properties(env)

    @staticmethod
    def _clear_invalidated_caches(
        registry: CacheInvalidating, before: dict[str, int]
    ) -> None:
        invalidated = tuple(
            name
            for name, generation in registry.cache_invalidation_generation.items()
            if generation != before.get(name, 0)
        )
        if invalidated:
            registry.clear_cache(*invalidated)


BaseCursor._savepoint_cls = _OrmSavepoint
BaseCursor._flushing_savepoint_cls = _OrmFlushingSavepoint
