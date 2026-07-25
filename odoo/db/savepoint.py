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
from typing import TYPE_CHECKING, Any, Protocol, Self, runtime_checkable

if TYPE_CHECKING:
    from .cursor import BaseCursor

_savepoint_counter = itertools.count()


@runtime_checkable
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

    _restores_orm_state: bool = False

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
