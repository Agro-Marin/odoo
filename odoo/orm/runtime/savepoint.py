"""ORM-aware flushing savepoint.

The ORM half of the savepoint machinery; the db half is in
:mod:`odoo.db.savepoint`.  :class:`_FlushingSavepoint` handles precommit
``flush()``; this subclass also restores ORM cache/environment state after a
``ROLLBACK TO SAVEPOINT``.  It lives here (not in :mod:`odoo.db`) to keep the
layering one-directional: the ORM depends on db, never the reverse.  Importing
the module registers the subclass on
:attr:`odoo.db.cursor.BaseCursor._flushing_savepoint_cls`.
"""

from __future__ import annotations

from odoo.db.cursor import BaseCursor
from odoo.db.savepoint import _FlushingSavepoint
from odoo.tools import reset_cached_properties


class _OrmFlushingSavepoint(_FlushingSavepoint):
    """:class:`_FlushingSavepoint` that also restores ORM state on rollback.

    Snapshots ``default_env`` and ``registry_sequence`` on creation; on rollback
    restores ``default_env`` and either resets the transaction (if the registry
    was reloaded inside the savepoint) or clears the cache and resets each
    environment's cached properties.
    """

    __slots__ = ("_saved_default_env", "_saved_registry_seq")

    def _save_orm_state(self, cr: BaseCursor) -> None:
        # default_env and registry_sequence are the only durable state; cache /
        # compute state is ephemeral (clear() handles it).
        txn = cr.transaction
        self._saved_default_env = txn.default_env if txn else None
        self._saved_registry_seq = txn.registry.registry_sequence if txn else -1

    def _restore_orm_state(self, cr: BaseCursor) -> None:
        # Only called by the base class when a transaction is attached.
        txn = cr.transaction
        txn.default_env = self._saved_default_env
        # Registry reloaded inside the savepoint: full reset.
        if txn.registry.registry_sequence != self._saved_registry_seq:
            txn.reset()
        else:
            txn.clear()
            for env in txn.envs:
                reset_cached_properties(env)


# Make cr.savepoint(flush=True) use the ORM-aware variant once the ORM is
# imported.  Before this, the db layer's plain _FlushingSavepoint is the default
# — fine, since no transaction is ever attached without the ORM.
BaseCursor._flushing_savepoint_cls = _OrmFlushingSavepoint
