"""Savepoint reification for :class:`~odoo.db.cursor.BaseCursor`.

Split out of :mod:`odoo.db.cursor` so the savepoint machinery lives in a small,
independently navigable unit.  Both classes are re-exported from
:mod:`odoo.db.cursor` for backwards compatibility.

``Savepoint`` is purely SQL (``SAVEPOINT`` / ``ROLLBACK TO`` / ``RELEASE``) and
has no ORM knowledge.  ``_FlushingSavepoint`` adds the precommit ``flush()`` —
the same minimal transaction surface :class:`BaseCursor` already touches in
``flush()`` / ``commit()`` / ``rollback()``.  It deliberately knows **nothing**
about ORM cache/environment
state: the deep reaches that restore it on rollback (``default_env``,
``registry.registry_sequence``, ``envs``, ``clear()`` / ``reset()`` and
``reset_cached_properties``) live in the ORM layer's
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
    """Reifies an active breakpoint, allows :meth:`BaseCursor.savepoint` users
    to internally rollback the savepoint (as many times as they want) without
    having to implement their own savepointing, or triggering exceptions.

    Should normally be created using :meth:`BaseCursor.savepoint` rather than
    directly.

    The savepoint will be rolled back on unsuccessful context exits
    (exceptions). It will be released ("committed") on successful context exit.
    The savepoint object can be wrapped in ``contextlib.closing`` to
    unconditionally roll it back.

    The savepoint can also safely be explicitly closed during context body. This
    will rollback by default.

    :param BaseCursor cr: the cursor to execute the `SAVEPOINT` queries on
    """

    __slots__ = ("_cr", "closed", "name")

    def __init__(self, cr: BaseCursor):
        self.name = f"sp{next(_savepoint_counter)}"
        self._cr = cr
        self.closed: bool = False
        # NB: f-string SQL is safe here — name is always "sp{int}" from our
        # own counter, never user input.  psycopg.sql.Identifier would add
        # overhead (quote + adapt) for zero security benefit.
        cr.execute(f'SAVEPOINT "{self.name}"')
        # Bump the cursor-level open-savepoint depth that
        # ``Cursor.commit``/``rollback`` guard on (see
        # ``BaseCursor._savepoint_depth``).  Tracked here, in the base class, so
        # EVERY savepoint counts — flushing or not, ORM-attached or bare.
        # Incremented only AFTER the SAVEPOINT SQL succeeds: a failed SAVEPOINT
        # must leave the depth at 0 (the object is never handed back, so _close
        # never runs to balance it).
        #
        # The ``hasattr`` guard covers ``TestCursor._check_savepoint``, which
        # reuses this class with a RAW psycopg cursor (``self._cursor._obj``) for
        # its internal transaction-simulating savepoint — deliberately, to keep
        # that SQL out of the query counts / profiler.  A raw psycopg cursor has
        # no ``_savepoint_depth`` and is never routed through Odoo's
        # commit/rollback guard, so the bookkeeping is both impossible and
        # unnecessary for it.  ``_close`` applies the symmetric guard.
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
        self._cr.execute(f'ROLLBACK TO SAVEPOINT "{self.name}"')

    def _close(self, rollback: bool) -> None:
        try:
            if rollback:
                self.rollback()
            self._cr.execute(f'RELEASE SAVEPOINT "{self.name}"')
            self.closed = True
        finally:
            # Balance __init__'s +1.  A ROLLBACK TO / RELEASE failure must still
            # drop the cursor depth — otherwise the leaked count wedges every
            # later commit/rollback on the guard.  _close runs at most once
            # (gated by close()'s ``not self.closed``), and only on a savepoint
            # whose SAVEPOINT SQL succeeded, so this never under-counts below 0.
            # The ``hasattr`` guard is symmetric with __init__'s — see there for
            # the raw-psycopg-cursor (TestCursor) case it covers.
            if hasattr(self._cr, "_savepoint_depth"):
                self._cr._savepoint_depth -= 1


class _FlushingSavepoint(Savepoint):
    """Savepoint that flushes precommit work.

    On creation, runs ``cr.flush()`` so queued precommit work lands *inside* the
    savepoint; on successful close it flushes again.  The open-savepoint depth
    the commit/rollback guard reads is the *cursor*-level
    :attr:`BaseCursor._savepoint_depth` that the base :class:`Savepoint` bumps
    for every savepoint (ORM-attached or bare) — see there — so the guard does
    not depend on a transaction being attached.

    ORM cache/environment restoration on rollback is **not** done here: when a
    transaction is attached (only the ORM attaches one), it is layered on by
    :class:`odoo.orm.runtime.savepoint._OrmFlushingSavepoint` through the
    :meth:`_save_orm_state` / :meth:`_restore_orm_state` hooks, which are no-ops
    at this (db) layer.
    """

    __slots__ = ()

    def __init__(self, cr: BaseCursor) -> None:
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
        # self._cr is always a BaseCursor here (savepoint() passes the cursor
        # itself); typed as such on Savepoint.__init__, so cr.transaction below
        # resolves without a runtime isinstance narrowing assert.
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
            # the cursor-level ``_savepoint_depth`` unconditionally (even on a
            # RELEASE failure) — see there.
            super()._close(rollback)
