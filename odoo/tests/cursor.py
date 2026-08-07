import contextlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import odoo
from odoo.db import BaseCursor, Cursor, Savepoint
from odoo.db.cursor import _logger

if TYPE_CHECKING:
    import threading


class TestCursor(BaseCursor):
    __test__ = False

    _cursors_stack: list[TestCursor] = []

    def __init__(self, cursor: Cursor, lock: threading.RLock, readonly: bool) -> None:
        assert isinstance(cursor, BaseCursor)
        super().__init__()
        self._now: datetime | None = None
        self._closed: bool = False
        self._cursor = cursor
        self.readonly = readonly
        self._lock = lock
        current_test = odoo.modules.module.current_test
        assert current_test, "Test Cursor without active test ?"
        current_test.assertCanOpenTestCursor()
        lock_timeout = current_test.test_cursor_lock_timeout
        if not self._lock.acquire(timeout=lock_timeout):
            raise Exception(
                f"Unable to acquire lock for test cursor after {lock_timeout}s"
            )
        try:
            current_test.assertCanOpenTestCursor()
            self._check_cursor_readonly()
        except Exception:
            self._lock.release()
            raise
        self._cursors_stack.append(self)
        self._savepoint: Savepoint | None = None

    def _check_cursor_readonly(self) -> None:
        last_cursor = self._cursors_stack and self._cursors_stack[-1]
        if (
            last_cursor
            and last_cursor.readonly
            and not self.readonly
            and last_cursor._savepoint
        ):
            raise Exception("Opening a read/write test cursor from a readonly one")

    def _check_savepoint(self) -> None:
        if not self._savepoint:
            self._savepoint = Savepoint(self._cursor._obj)
            if self.readonly:
                self._cursor._obj.execute("SET TRANSACTION READ ONLY")

    def _close_savepoint(self, *, rollback: bool) -> None:
        if not self._savepoint:
            return
        self._savepoint.close(rollback=rollback)
        self._savepoint = None
        if rollback:
            self._cursor._on_rollback_to_savepoint()

    def _statement(self, name: str, args: tuple, kwargs: dict) -> Any:
        assert not self._closed, "Cannot use a closed cursor"
        self._check_savepoint()
        return getattr(self._cursor, name)(*args, **kwargs)

    def execute(self, *args: Any, **kwargs: Any) -> None:
        return self._statement("execute", args, kwargs)

    def executemany(self, *args: Any, **kwargs: Any) -> None:
        return self._statement("executemany", args, kwargs)

    def execute_values(self, *args: Any, **kwargs: Any) -> Any:
        return self._statement("execute_values", args, kwargs)

    def copy_from(self, *args: Any, **kwargs: Any) -> Any:
        return self._statement("copy_from", args, kwargs)

    def copy(self, *args: Any, **kwargs: Any) -> Any:
        return self._statement("copy", args, kwargs)

    def close(self) -> None:
        if not self._closed:
            try:
                self.rollback()
            finally:
                self._closed = True

                if self._cursors_stack and self._cursors_stack[-1] is self:
                    self._cursors_stack.pop()
                else:
                    _logger.warning(
                        "Out-of-order close: %s is not the top of the cursor stack",
                        self,
                    )
                    with contextlib.suppress(ValueError):
                        self._cursors_stack.remove(self)
                self._lock.release()

    def commit(self) -> None:
        self.flush()
        self._close_savepoint(rollback=self.readonly)
        self.commit_count += 1
        self.clear()
        self._now = None
        self.prerollback.clear()
        self.postrollback.clear()
        self.postcommit.clear()

    def rollback(self) -> None:
        self.clear()
        self._now = None
        self.postcommit.clear()
        self.prerollback.run()
        self._close_savepoint(rollback=True)
        self.postrollback.run()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._cursor, name)

    def dictfetchone(self) -> dict | None:
        return self._cursor.dictfetchone()

    def dictfetchmany(self, size: int) -> list[dict]:
        return self._cursor.dictfetchmany(size)

    def dictfetchall(self) -> list[dict]:
        return self._cursor.dictfetchall()

    def now(self) -> datetime:
        if self._now is None:
            self._now = datetime.now(UTC).replace(tzinfo=None)
        return self._now
