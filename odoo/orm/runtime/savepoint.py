from __future__ import annotations

import typing
from typing import Protocol

from odoo.db.cursor import BaseCursor
from odoo.db.savepoint import _FlushingSavepoint
from odoo.tools import reset_cached_properties

_NO_SNAPSHOT: typing.Final = object()


class CacheInvalidating(Protocol):
    """The two members `_reclear_invalidated_caches` reads off a registry.

    Narrower than `Registry` for the reason `db.savepoint.SavepointHost` is
    narrower than a cursor: a signature that names the whole class claims a
    dependency the function does not have, and makes every honest stand-in --
    the fake this method's own test drives it with -- a lie to the checker.
    """

    @property
    def cache_invalidated(self) -> set[str]: ...

    def clear_cache(self, *names: str) -> None: ...


class _OrmFlushingSavepoint(_FlushingSavepoint):
    __slots__ = ("_saved_default_env",)

    _restores_orm_state = True

    def _save_orm_state(self, cr: BaseCursor) -> None:
        txn = cr.transaction
        self._saved_default_env = txn.default_env if txn else _NO_SNAPSHOT

    def _restore_orm_state(self, cr: BaseCursor) -> None:
        txn = cr.transaction
        if txn is None:
            # `_save_orm_state` above already treats a cursor with no
            # transaction as having no ORM state to snapshot; restoring one
            # would be restoring nothing, and every line below would reach
            # through the None it explicitly allows for.
            return
        if self._saved_default_env is not _NO_SNAPSHOT:
            txn.default_env = self._saved_default_env
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
        """Drop registry caches this transaction refilled from rolled-back rows.

        `clear_cache` runs inline in `create` / `write` / `unlink`, so anything read
        after it and before the commit repopulates a *registry-wide* LRU from data
        only this transaction can see. A full rollback is covered --
        `Registry.reset_changes` re-clears every group in `cache_invalidated` -- and
        a commit is covered because the values were true. A savepoint rollback was
        covered by neither: `Cursor._on_rollback_to_savepoint` clears the schema
        cache and nothing else, so the phantom value stayed for the life of the
        worker. Nothing re-clears it later either, because `signal_changes` only
        bumps `orm_signaling_<group>` to tell *other* processes.

        Reproduced against `ir.config_parameter`, whose `_get_param` is cached on the
        same bucket: write inside a savepoint, roll it back, and `get_param` answers
        with the discarded value while the row holds the committed one.

        Clearing is over-eager on purpose -- the whole invalidated set goes, not the
        groups touched inside this savepoint -- because a group marked earlier can
        just as easily have been refilled from uncommitted rows inside it. Dropping a
        cache entry is never incorrect, only slower, and the set is empty in any
        transaction that wrote no cached model.
        """
        if invalidated := tuple(registry.cache_invalidated):
            # Through the public entry point, so `cache_invalidated` keeps naming the
            # groups and the commit still signals peers.
            registry.clear_cache(*invalidated)


BaseCursor._flushing_savepoint_cls = _OrmFlushingSavepoint
