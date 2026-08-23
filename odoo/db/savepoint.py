from __future__ import annotations

import itertools
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Protocol, Self

import psycopg.errors

if TYPE_CHECKING:
    from .cursor import BaseCursor

_savepoint_counter = itertools.count()


class SavepointHost(Protocol):
    def execute(self, query: Any, /, *args: Any, **kwargs: Any) -> Any: ...


class Savepoint:
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
    __slots__ = ()

    if TYPE_CHECKING:
        _cr: BaseCursor

    def __init__(self, cr: BaseCursor) -> None:
        cr.flush()
        self._save_orm_state(cr)
        super().__init__(cr)

    def _save_orm_state(self, cr: BaseCursor) -> None:
        pass

    def _restore_orm_state(self, cr: BaseCursor) -> None:
        pass

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
