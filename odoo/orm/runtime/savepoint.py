"""ORM-aware flushing savepoint.

This is the ORM half of the savepoint machinery whose db half lives in
:mod:`odoo.db.savepoint`.  :class:`odoo.db.savepoint._FlushingSavepoint` handles
the database-level concern (precommit ``flush()``); this subclass adds the
restoration of ORM cache/environment state after a ``ROLLBACK TO SAVEPOINT`` —
the only place
that needs the deep :class:`~odoo.orm.runtime.transaction.Transaction` internals
(``default_env``, ``registry.registry_sequence``, ``envs``, ``clear()`` /
``reset()`` and ``reset_cached_properties``).

Keeping it here — rather than in :mod:`odoo.db` — makes the layering
one-directional: the ORM depends on the db package, never the reverse.  Importing
this module registers the subclass as
:attr:`odoo.db.cursor.BaseCursor._flushing_savepoint_cls`, so
``cr.savepoint(flush=True)`` returns it whenever the ORM is loaded.
"""

from __future__ import annotations

from odoo.db.cursor import BaseCursor
from odoo.db.savepoint import _FlushingSavepoint
from odoo.tools import reset_cached_properties


class _OrmFlushingSavepoint(_FlushingSavepoint):
    """:class:`_FlushingSavepoint` that also restores ORM state on rollback.

    On creation it snapshots the transaction's ``default_env`` and
    ``registry_sequence``; on rollback it restores ``default_env`` and either
    fully resets the transaction (if the registry was reloaded inside the
    savepoint) or clears its cache and resets each environment's cached
    properties — so the ORM view of the world matches the database state after
    ``ROLLBACK TO SAVEPOINT``.
    """

    __slots__ = ("_saved_default_env", "_saved_registry_seq")

    def _save_orm_state(self, cr: BaseCursor) -> None:
        # Save ORM state that must survive rollback.  Cache/compute state is
        # ephemeral — clear() handles it.  default_env and registry_sequence
        # are the only durable state.
        txn = cr.transaction
        self._saved_default_env = txn.default_env if txn else None
        self._saved_registry_seq = txn.registry.registry_sequence if txn else -1

    def _restore_orm_state(self, cr: BaseCursor) -> None:
        # Only called by the base class when a transaction is attached.
        txn = cr.transaction
        # Restore default_env to its pre-savepoint value.
        txn.default_env = self._saved_default_env
        # If the registry was reloaded inside the savepoint, full reset.
        if txn.registry.registry_sequence != self._saved_registry_seq:
            txn.reset()
        else:
            txn.clear()
            for env in txn.envs:
                reset_cached_properties(env)


# Register so cr.savepoint(flush=True) uses the ORM-aware variant whenever the
# ORM layer is imported.  Before this runs, the db layer's plain
# _FlushingSavepoint is the default — correct, because no transaction is ever
# attached without the ORM.
BaseCursor._flushing_savepoint_cls = _OrmFlushingSavepoint
