import contextlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import odoo
from odoo.db import BaseCursor, Cursor, Savepoint
from odoo.db.cursor import _logger

if TYPE_CHECKING:
    import threading


class TestCursor(BaseCursor):
    """A pseudo-cursor to be used for tests, on top of a real cursor. It keeps
    the transaction open across requests, and simulates committing, rolling
    back, and closing:

    +------------------------+---------------------------------------------------+
    |  test cursor           | queries on actual cursor                          |
    +========================+===================================================+
    |``cr = TestCursor(...)``|                                                   |
    +------------------------+---------------------------------------------------+
    | ``cr.execute(query)``  | SAVEPOINT test_cursor_N (if not savepoint)        |
    |                        | query                                             |
    +------------------------+---------------------------------------------------+
    |  ``cr.commit()``       | RELEASE SAVEPOINT test_cursor_N (if savepoint)    |
    +------------------------+---------------------------------------------------+
    |  ``cr.rollback()``     | ROLLBACK TO SAVEPOINT test_cursor_N (if savepoint)|
    +------------------------+---------------------------------------------------+
    |  ``cr.close()``        | ROLLBACK TO SAVEPOINT test_cursor_N (if savepoint)|
    |                        | RELEASE SAVEPOINT test_cursor_N (if savepoint)    |
    +------------------------+---------------------------------------------------+
    """

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
        """Raise if opening a read/write cursor from within a readonly one.

        Only enforced once the readonly cursor has actually started its
        transaction (its savepoint is created lazily on first execute): an
        untouched readonly cursor constrains nothing.
        """
        last_cursor = self._cursors_stack and self._cursors_stack[-1]
        if (
            last_cursor
            and last_cursor.readonly
            and not self.readonly
            and last_cursor._savepoint
        ):
            raise Exception("Opening a read/write test cursor from a readonly one")

    def _check_savepoint(self) -> None:
        """Create the internal savepoint lazily on first use."""
        if not self._savepoint:
            self._savepoint = Savepoint(self._cursor._obj)
            if self.readonly:
                self._cursor._obj.execute("SET TRANSACTION READ ONLY")

    def _close_savepoint(self, *, rollback: bool) -> None:
        """Release or roll back the internal savepoint, notifying the cursor.

        Single place that ends the savepoint, because a ``ROLLBACK TO
        SAVEPOINT`` releases the locks taken inside it and the wrapped cursor
        caches catalog facts that rest on those locks.  ``rollback()`` notified
        it; ``commit()`` on a readonly cursor — which also rolls back — did not.
        """
        if not self._savepoint:
            return
        self._savepoint.close(rollback=rollback)
        self._savepoint = None
        if rollback:
            self._cursor._on_rollback_to_savepoint()

    def _statement(self, name: str, args: tuple, kwargs: dict) -> Any:
        """Forward a statement to the real cursor, behind this cursor's savepoint.

        Every entry point :class:`~odoo.db.cursor.Cursor` marks with
        ``_before_statement`` must come through here.  Only ``execute`` used to,
        so ``executemany`` / ``execute_values`` / ``copy_from`` — which this
        class does not override, and which therefore reach the real cursor via
        :meth:`__getattr__` — wrote outside the savepoint and survived the test
        rollback.

        The savepoint cannot be taken by hooking the wrapped cursor instead:
        several test cursors share one real cursor, so a hook installed there
        would open whichever test cursor happens to be innermost, not the one
        the caller is using.
        ``TestTestCursorContainsBulkWrites.test_every_marked_entry_point_is_forwarded_by_the_wrapper``
        pins the two lists against each other so a new write API cannot quietly
        skip this.
        """
        assert not self._closed, "Cannot use a closed cursor"
        self._check_savepoint()
        return getattr(self._cursor, name)(*args, **kwargs)

    def execute(self, *args: Any, **kwargs: Any) -> None:
        """Execute a query, creating the savepoint if needed."""
        return self._statement("execute", args, kwargs)

    def executemany(self, *args: Any, **kwargs: Any) -> None:
        """Batch-execute a query, creating the savepoint if needed."""
        return self._statement("executemany", args, kwargs)

    def execute_values(self, *args: Any, **kwargs: Any) -> Any:
        """Expand a VALUES list, creating the savepoint if needed."""
        return self._statement("execute_values", args, kwargs)

    def copy_from(self, *args: Any, **kwargs: Any) -> Any:
        """Bulk-insert via COPY, creating the savepoint if needed."""
        return self._statement("copy_from", args, kwargs)

    def copy(self, *args: Any, **kwargs: Any) -> Any:
        """Open a raw COPY context, creating the savepoint if needed."""
        return self._statement("copy", args, kwargs)

    def close(self) -> None:
        """Roll back to the savepoint and release the lock."""
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
        """Perform an SQL ``COMMIT``.

        Deliberately NOT guarded by ``_savepoint_depth`` (unlike the production
        ``Cursor.commit``): ``TransactionCase.setUp`` wraps every test body in a
        ``Savepoint(self.cr)`` on this cursor, so the depth is >= 1 for the
        whole test and the guard would reject every legitimate simulated
        commit.  The real protection lives in ``TransactionCase.setUpClass``,
        which patches the class cursor's commit/rollback/close to raise.
        """
        self.flush()
        self._close_savepoint(rollback=self.readonly)
        # Mirrors Cursor.commit: bumped once the simulated commit has taken
        # effect, so retrying() classifies a failure the same way here as in
        # production (a post-commit failure after this point is "durable", not
        # "the commit failed").  Without it the test tier would silently take
        # the other branch.
        self.commit_count += 1
        self.clear()
        self._now = None
        self.prerollback.clear()
        self.postrollback.clear()
        self.postcommit.clear()

    def rollback(self) -> None:
        """Perform an SQL ``ROLLBACK``.

        Not guarded by ``_savepoint_depth`` — see :meth:`commit`.
        """
        self.clear()
        self._now = None
        self.postcommit.clear()
        self.prerollback.run()
        self._close_savepoint(rollback=True)
        self.postrollback.run()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._cursor, name)

    def dictfetchone(self) -> dict | None:
        """Return the first row as a dict (column_name -> value) or None if no rows are available."""
        return self._cursor.dictfetchone()

    def dictfetchmany(self, size: int) -> list[dict]:
        """Return the next ``size`` rows as a list of dicts."""
        return self._cursor.dictfetchmany(size)

    def dictfetchall(self) -> list[dict]:
        """Return all remaining rows as a list of dicts."""
        return self._cursor.dictfetchall()

    def now(self) -> datetime:
        """Return the transaction's timestamp as naive UTC.

        Mirrors the real :meth:`Cursor.now` (``SELECT now() AT TIME ZONE
        'UTC'``) so test-created ``create_date``/``write_date`` carry the same
        UTC semantics as production.  ``datetime.now()`` (local, naive) made
        records on a non-UTC host land hours off — invisible under UTC CI but
        wrong on developer machines.  The Python clock is used instead of a SQL
        query to keep the savepoint/query counts clean.
        """
        if self._now is None:
            self._now = datetime.now(UTC).replace(tzinfo=None)
        return self._now
