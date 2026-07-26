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
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Protocol, Self

import psycopg.errors

if TYPE_CHECKING:
    from .cursor import BaseCursor

_savepoint_counter = itertools.count()


class SavepointHost(Protocol):
    """What :class:`Savepoint` actually requires of the object it is given.

    Deliberately *not* ``BaseCursor``.  ``Savepoint`` was annotated that way,
    but ``TestCursor._check_savepoint`` constructs one over a **raw
    ``psycopg.Cursor``** — on purpose, so the SAVEPOINT/RELEASE statements stay
    out of the query counts and the profiler.  The annotation was therefore a
    lie the type checker reported on every such call site, and the two
    ``hasattr``/``getattr`` guards below read as defensive noise instead of what
    they are: the runtime half of an optional-member contract.

    Naming that contract makes both halves honest — ``execute`` is required,
    ``_savepoint_depth`` and ``_on_rollback_to_savepoint`` are the extras a full
    :class:`~odoo.db.cursor.BaseCursor` adds and a raw cursor does not.

    Deliberately not ``@runtime_checkable``: nothing ``isinstance``-checks it,
    and the decorator would advertise a structural check that would in any case
    only verify ``execute`` exists — not the optional members that are the whole
    reason this Protocol is written down.
    """

    def execute(self, query: Any, /, *args: Any, **kwargs: Any) -> Any:
        """Run one statement.  The only member every host must provide."""
        ...


class Savepoint:
    """Reifies an active savepoint so callers can roll it back repeatedly
    without managing their own savepoint SQL or handling exceptions.

    Normally created via :meth:`BaseCursor.savepoint`, not directly.  As a
    context manager it rolls back on an exceptional exit and releases
    ("commits") on a clean one; wrap it in ``contextlib.closing`` to roll back
    unconditionally.  It may also be closed explicitly inside the body (rolls
    back by default).

    :param SavepointHost cr: anything that can ``execute`` a statement — a
        :class:`~odoo.db.cursor.BaseCursor`, or the raw psycopg cursor
        ``TestCursor`` uses to keep this SQL out of the query counts.
    """

    __slots__ = ("_cr", "closed", "name")

    _restores_orm_state: bool = False

    def __init__(self, cr: SavepointHost):
        self.name = f"sp{next(_savepoint_counter)}"
        self._cr = cr
        self.closed: bool = False
        cr.execute(f'SAVEPOINT "{self.name}"')
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
        if self.closed:
            raise RuntimeError(
                f'Savepoint "{self.name}" is already closed; cannot roll back'
            )
        self._cr.execute(f'ROLLBACK TO SAVEPOINT "{self.name}"')
        notify = getattr(self._cr, "_on_rollback_to_savepoint", None)
        if notify is not None:
            notify()

    def _close(self, rollback: bool) -> None:
        try:
            if rollback:
                self.rollback()
            self._cr.execute(f'RELEASE SAVEPOINT "{self.name}"')
        finally:
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

    if TYPE_CHECKING:
        _cr: BaseCursor

    def __init__(self, cr: BaseCursor) -> None:
        cr.flush()
        self._save_orm_state(cr)
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
        super().rollback()
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
            super()._close(rollback)


def insert_or_existing[T](
    cr: Any,
    insert: Callable[[], T],
    find: Callable[[], T],
    *,
    conflict: str,
) -> tuple[T, bool]:
    """Run *insert*, falling back to *find* when a unique constraint rejects it.

    The one correct shape for "create this row unless it already exists" under
    Odoo's ``REPEATABLE READ`` cursors, where the obvious spelling is wrong in a
    way that only shows up under concurrency:

    * *insert* runs inside a savepoint, so a rejection leaves the caller's
      transaction usable rather than aborted;
    * ``ROLLBACK TO SAVEPOINT`` does **not** refresh the transaction snapshot,
      so *find* can only see a row this transaction could already see -- one an
      earlier statement missed, or one it wrote itself.  It is the right
      recovery for that case and returns it;
    * a row a *concurrent* transaction committed after this snapshot began is
      invisible to *find* no matter what, so there is nothing local to recover
      to.  That raises :class:`~odoo.exceptions.ConcurrencyError`, which
      ``odoo.service.transaction.retrying`` answers by replaying the whole
      request against a fresh snapshot.

    Re-running *insert*, or returning whatever empty value *find* produced, were
    both tried in this codebase and both surfaced as user-visible failures --
    a duplicate-key error and a query against ``id = False`` respectively.

    Callers that must tell the two apart -- "no previous value" reads very
    differently from "here is the previous value" -- get it from the returned
    flag rather than by watching *insert*: the constraint is enforced when the
    savepoint flushes, which can be after *insert* has returned, so a flag it
    sets itself says the row was created when it was not.

    :param insert: performs the insert and returns the new row
    :param find: looks the row up again; falsy when this snapshot cannot see it
    :param conflict: what collided, for the ``ConcurrencyError`` message
    :return: ``(row, created)`` -- *created* is ``False`` when *find* supplied
        the row
    """
    from odoo.exceptions import ConcurrencyError

    try:
        with cr.savepoint():
            return insert(), True
    except psycopg.errors.UniqueViolation:
        existing = find()
        if not existing:
            raise ConcurrencyError(
                f"{conflict} was created by a concurrent transaction"
            ) from None
        return existing, False
