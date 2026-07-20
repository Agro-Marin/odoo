"""Savepoint reification for :class:`~odoo.db.cursor.BaseCursor`.

Split out of :mod:`odoo.db.cursor`; both classes are re-exported from there for
backwards compatibility.

``Savepoint`` is purely SQL (``SAVEPOINT`` / ``ROLLBACK TO`` / ``RELEASE``) and
has no ORM knowledge.  ``_FlushingSavepoint`` adds the precommit ``flush()`` but
deliberately knows nothing about ORM cache/environment state: restoring that on
rollback lives in the ORM's
:class:`odoo.orm.runtime.savepoint._OrmFlushingSavepoint`, which subclasses this
via the ``_save_orm_state`` / ``_restore_orm_state`` hooks and registers itself
as ``BaseCursor._flushing_savepoint_cls`` on import.  This keeps the db→ORM
dependency one-directional.
"""

from __future__ import annotations

import itertools
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from .cursor import BaseCursor

# Monotonic counter for savepoint names (thread-safe via CPython's GIL).
_savepoint_counter = itertools.count()


class Savepoint:
    """Reifies an active savepoint so callers can roll it back repeatedly
    without managing their own savepoint SQL or handling exceptions.

    Normally created via :meth:`BaseCursor.savepoint`, not directly.  As a
    context manager it rolls back on an exceptional exit and releases
    ("commits") on a clean one; wrap it in ``contextlib.closing`` to roll back
    unconditionally.  It may also be closed explicitly inside the body (rolls
    back by default).

    :param BaseCursor cr: the cursor to execute the ``SAVEPOINT`` queries on
    """

    __slots__ = ("_cr", "closed", "name")

    def __init__(self, cr: BaseCursor):
        self.name = f"sp{next(_savepoint_counter)}"
        self._cr = cr
        self.closed: bool = False
        # f-string SQL is safe: name is always "sp{int}" from our counter, never
        # user input.  Identifier would add quote/adapt overhead for no benefit.
        cr.execute(f'SAVEPOINT "{self.name}"')
        # Bump the cursor-level open-savepoint depth the commit/rollback guard
        # reads (see ``BaseCursor._savepoint_depth``).  After the SQL succeeds, so
        # a failed SAVEPOINT leaves the depth at 0.  The ``hasattr`` guard covers
        # ``TestCursor._check_savepoint``, which reuses this class with a raw
        # psycopg cursor (no ``_savepoint_depth``); ``_close`` mirrors it.
        if hasattr(cr, "_savepoint_depth"):
            cr._savepoint_depth += 1

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        self.close(rollback=exc_type is not None)

    def close(self, *, rollback: bool = True) -> None:
        if not self.closed:
            self._close(rollback)

    def rollback(self) -> None:
        # Guard against rolling back a closed savepoint: its name has been
        # RELEASEd, so ``ROLLBACK TO`` would abort the whole outer transaction
        # with InvalidSavepointSpecification.  ``_close`` calls this *before*
        # marking closed, so its internal rollback is unaffected.
        if self.closed:
            raise RuntimeError(
                f'Savepoint "{self.name}" is already closed; cannot roll back'
            )
        self._cr.execute(f'ROLLBACK TO SAVEPOINT "{self.name}"')

    def _close(self, rollback: bool) -> None:
        try:
            if rollback:
                self.rollback()
            self._cr.execute(f'RELEASE SAVEPOINT "{self.name}"')
        finally:
            # Mark closed and balance __init__'s +1 exactly once — even on a
            # ROLLBACK TO / RELEASE failure.  A failed close leaves the savepoint
            # in an unknown state (e.g. released behind our back), so it must NOT
            # be retried: a second _close would ROLLBACK TO a released name
            # (aborting the outer transaction) AND decrement the depth again,
            # driving it negative and permanently wedging commit()/rollback().
            # Setting ``closed`` here makes the ``close()`` gate a no-op on retry.
            # ``hasattr`` guard mirrors __init__'s (TestCursor._check_savepoint).
            self.closed = True
            if hasattr(self._cr, "_savepoint_depth"):
                self._cr._savepoint_depth -= 1


class _FlushingSavepoint(Savepoint):
    """Savepoint that flushes precommit work.

    On creation runs ``cr.flush()`` *before* opening the savepoint, so work
    already pending from before it is persisted into the OUTER transaction and
    is therefore NOT undone by a later ``ROLLBACK TO SAVEPOINT``.  On successful
    close it flushes again — that second flush runs while the savepoint is still
    open (before ``RELEASE``), so work done inside the block does land inside the
    savepoint.  ORM cache/environment restoration on rollback is layered on by
    the ORM's :class:`~odoo.orm.runtime.savepoint._OrmFlushingSavepoint` via the
    :meth:`_save_orm_state` / :meth:`_restore_orm_state` hooks (no-ops here).
    """

    __slots__ = ()

    # Whether ``_restore_orm_state`` actually restores the ORM cache/env on
    # rollback.  False here (the hooks are no-ops); the ORM subclass sets it
    # True.  ``BaseCursor.savepoint`` asserts on it so a transaction-bearing
    # cursor can never silently use this non-restoring base (see that method).
    _restores_orm_state: bool = False

    def __init__(self, cr: BaseCursor) -> None:
        # Flush BEFORE the SAVEPOINT is opened (super().__init__ below): this
        # drains pre-existing pending work into the outer transaction so the
        # savepoint captures only work done inside the block.  The in-block work
        # is kept by the second flush in _close().
        cr.flush()
        # ORM hook: snapshot any state that must be restored on rollback.
        self._save_orm_state(cr)
        # Base ``Savepoint.__init__`` issues the SAVEPOINT SQL and bumps the
        # cursor-level ``_savepoint_depth`` (only after the SQL succeeds) — the
        # single counter the commit/rollback guard reads.
        super().__init__(cr)

    def _save_orm_state(self, cr: BaseCursor) -> None:
        """Hook: snapshot ORM state needed to restore on rollback.

        No-op at the db layer; overridden by the ORM's subclass.
        """

    def _restore_orm_state(self, cr: BaseCursor) -> None:
        """Hook: restore ORM state after ``ROLLBACK TO SAVEPOINT``.

        No-op at the db layer; overridden by the ORM's subclass.  Only called
        when a transaction is attached.
        """

    def rollback(self) -> None:
        cr = self._cr
        super().rollback()  # SQL ROLLBACK TO SAVEPOINT first
        if cr.transaction is not None:
            self._restore_orm_state(cr)

    def _close(self, rollback: bool) -> None:
        cr = self._cr
        try:
            if not rollback:
                cr.flush()
        except Exception:
            rollback = True
            raise
        finally:
            # Base ``Savepoint._close`` issues ROLLBACK TO / RELEASE and balances
            # ``_savepoint_depth`` (see there).
            super()._close(rollback)
