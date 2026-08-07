from __future__ import annotations

import typing

from odoo.db.cursor import BaseCursor
from odoo.db.savepoint import _FlushingSavepoint
from odoo.tools import reset_cached_properties

_NO_SNAPSHOT: typing.Final = object()


class _OrmFlushingSavepoint(_FlushingSavepoint):
    __slots__ = ("_saved_default_env",)

    _restores_orm_state = True

    def _save_orm_state(self, cr: BaseCursor) -> None:
        txn = cr.transaction
        self._saved_default_env = txn.default_env if txn else _NO_SNAPSHOT

    def _restore_orm_state(self, cr: BaseCursor) -> None:
        txn = cr.transaction
        if self._saved_default_env is not _NO_SNAPSHOT:
            txn.default_env = self._saved_default_env
        current = type(txn.registry).registries.get(txn.registry.db_name)
        if current is not None and current is not txn.registry:
            txn.reset()
        else:
            txn.clear()
            for env in txn.envs:
                reset_cached_properties(env)


BaseCursor._flushing_savepoint_cls = _OrmFlushingSavepoint
