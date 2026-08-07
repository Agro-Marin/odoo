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

import typing

from odoo.db.cursor import BaseCursor
from odoo.db.savepoint import _FlushingSavepoint
from odoo.tools import reset_cached_properties

#: "There was no transaction when this savepoint opened", as distinct from
#: "``default_env`` was ``None``".  Collapsing the two let a rollback write
#: ``None`` over a ``default_env`` that had been established *inside* the
#: savepoint, which puts the transaction permanently into
#: ``Transaction.flush``'s degraded branch — it fabricates a SUPERUSER
#: environment to flush with, so a user's pending writes get flushed with the
#: wrong user, company and record-rule context, warning but not failing.
_NO_SNAPSHOT: typing.Final = object()


class _OrmFlushingSavepoint(_FlushingSavepoint):
    """:class:`_FlushingSavepoint` that also restores ORM state on rollback.

    Snapshots ``default_env`` on creation; on rollback restores it and either
    resets the transaction (if the registry was reloaded inside the savepoint —
    detected by object identity against ``Registry.registries``, see
    :meth:`_restore_orm_state`) or clears the cache and resets each
    environment's cached properties.
    """

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
