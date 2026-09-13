import contextlib
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

import odoo
from odoo.db import BaseCursor, Cursor, Savepoint
from odoo.libs.debug_log import DebugLog

if TYPE_CHECKING:
    import threading

    from .common import BaseCase

_logger = logging.getLogger(__name__)
_debug = DebugLog(__name__)


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
        running = odoo.modules.module.current_test
        assert not isinstance(running, bool), "Test Cursor without active test ?"
        current_test = cast("BaseCase", running)
        current_test.assertCanOpenTestCursor()
        lock_timeout = current_test.test_cursor_lock_timeout
        with _debug.perf(
            "test.cursor.lock_wait",
            test=current_test.canonical_tag,
            timeout=lock_timeout,
            held=getattr(lock, "count", None),
        ) as span:
            acquired = self._lock.acquire(timeout=lock_timeout)
            span.set(acquired=acquired)
        if not acquired:
            _debug.logic(
                "test.cursor.lock_timeout",
                test=current_test.canonical_tag,
                timeout=lock_timeout,
                depth=len(self._cursors_stack),
            )
            raise Exception(
                f"Unable to acquire lock for test cursor after {lock_timeout}s"
            )
        try:
            current_test.assertCanOpenTestCursor()
            self._check_cursor_readonly()
            self._check_outer_savepoints()
        except Exception as exc:
            _debug.lifecycle(
                "test.cursor.open_refused",
                test=current_test.canonical_tag,
                error=type(exc).__name__,
            )
            self._lock.release()
            raise
        self._cursors_stack.append(self)
        self._savepoint: Savepoint | None = None
        _debug.lifecycle(
            "test.cursor.open",
            test=current_test.canonical_tag,
            readonly=readonly,
            depth=len(self._cursors_stack),
            held=getattr(lock, "count", None),
        )

    def _check_cursor_readonly(self) -> None:
        if self.readonly:
            return
        if any(cursor.readonly and cursor._savepoint for cursor in self._cursors_stack):
            _debug.logic(
                "test.cursor.readonly_violation", depth=len(self._cursors_stack)
            )
            raise Exception("Opening a read/write test cursor from a readonly one")

    def _check_outer_savepoints(self) -> None:
        # Every test cursor shares one connection, and a cursor takes its savepoint on
        # its first statement. An outer cursor whose first statement runs while this one
        # is open would nest its savepoint inside ours, and our rollback would destroy it.
        # Read-only cursors stay lazy: their savepoint sets the transaction read-only.
        forced = 0  # debuglog
        for cursor in self._cursors_stack:
            if not cursor.readonly:
                if not cursor._savepoint:
                    forced += 1  # debuglog
                cursor._check_savepoint()
        if forced:
            _debug.logic(
                "test.cursor.outer_savepoints_forced",
                forced=forced,
                depth=len(self._cursors_stack),
            )

    def _check_savepoint(self) -> None:
        if not self._savepoint:
            self._savepoint = Savepoint(self._cursor._obj)
            if self.readonly:
                self._cursor._obj.execute("SET TRANSACTION READ ONLY")
            _debug.lifecycle("test.cursor.savepoint_opened", readonly=self.readonly)

    def _close_savepoint(self, *, rollback: bool) -> None:
        if not self._savepoint:
            return
        self._savepoint.close(rollback=rollback)
        self._savepoint = None
        _debug.lifecycle("test.cursor.savepoint_closed", rollback=rollback)
        if rollback:
            self._cursor._on_rollback_to_savepoint()

    def _statement(self, name: str, args: tuple, kwargs: dict) -> Any:
        assert not self._closed, "Cannot use a closed cursor"
        self._check_savepoint()
        _debug.perf.count("test.cursor.statement", kind=name, readonly=self.readonly)
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
        if self._closed:
            _debug.logic("test.cursor.close_again")
            return
        try:
            self.rollback()
        finally:
            self._closed = True

            in_order = bool(
                self._cursors_stack and self._cursors_stack[-1] is self
            )  # debuglog
            if in_order:
                self._cursors_stack.pop()
            else:
                _debug.logic(
                    "test.cursor.close_out_of_order",
                    depth=len(self._cursors_stack),
                    on_stack=self in self._cursors_stack,
                )
                _logger.warning(
                    "Out-of-order close: %s is not the top of the cursor stack",
                    self,
                )
                with contextlib.suppress(ValueError):
                    self._cursors_stack.remove(self)
            self._lock.release()
            _debug.lifecycle(
                "test.cursor.close",
                readonly=self.readonly,
                in_order=in_order,
                depth=len(self._cursors_stack),
                commits=self.commit_count,
                held=getattr(self._lock, "count", None),
            )

    def commit(self) -> None:
        self.flush()
        self._close_savepoint(rollback=self.readonly)
        self.commit_count += 1
        self.clear()
        self._now = None
        self.prerollback.clear()
        self.postrollback.clear()
        self.postcommit.clear()
        _debug.lifecycle(
            "test.cursor.commit", readonly=self.readonly, commits=self.commit_count
        )

    def rollback(self) -> None:
        had_savepoint = self._savepoint is not None  # debuglog
        self.clear()
        self._now = None
        self.postcommit.clear()
        self.prerollback.run()
        self._close_savepoint(rollback=True)
        self.postrollback.run()
        _debug.lifecycle(
            "test.cursor.rollback", readonly=self.readonly, had_savepoint=had_savepoint
        )

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
