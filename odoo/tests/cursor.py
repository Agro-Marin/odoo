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

    # Not a pytest test class despite the "Test" prefix — it is a pseudo-cursor
    # utility.  Tell pytest never to collect it (it has an __init__, which would
    # otherwise raise a collection warning wherever this module is scanned).
    __test__ = False

    _cursors_stack: list[TestCursor] = []

    def __init__(self, cursor: Cursor, lock: threading.RLock, readonly: bool) -> None:
        assert isinstance(cursor, BaseCursor)
        super().__init__()
        self._now: datetime | None = None
        self._closed: bool = False
        self._cursor = cursor
        self.readonly = readonly
        # we use a lock to serialize concurrent requests
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
            # Check after acquiring in case current_test has changed.
            # This can happen if the request was hanging between two tests.
            current_test.assertCanOpenTestCursor()
            self._check_cursor_readonly()
        except Exception:
            self._lock.release()
            raise
        self._cursors_stack.append(self)
        # in order to simulate commit and rollback, the cursor maintains a
        # savepoint at its last commit, the savepoint is created lazily
        self._savepoint: Savepoint | None = None

    def _check_cursor_readonly(self) -> None:
        """Raise if opening a read/write cursor from within a readonly one."""
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
            # we use self._cursor._obj for the savepoint to avoid having the
            # savepoint queries in the query counts, profiler, ...
            # Those queries are tests artefacts and should be invisible.
            self._savepoint = Savepoint(self._cursor._obj)
            if self.readonly:
                # this will simulate a readonly connection
                self._cursor._obj.execute(
                    "SET TRANSACTION READ ONLY"
                )  # use _obj to avoid impacting query count and profiler.

    def execute(self, *args: Any, **kwargs: Any) -> None:
        """Execute a query, creating the savepoint if needed."""
        assert not self._closed, "Cannot use a closed cursor"
        self._check_savepoint()
        return self._cursor.execute(*args, **kwargs)

    def close(self) -> None:
        """Roll back to the savepoint and release the lock."""
        if not self._closed:
            try:
                # rollback() rolls back to *and* releases the savepoint, then
                # nulls self._savepoint -- so there is nothing left to release here.
                self.rollback()
            finally:
                self._closed = True

                # Remove *this* cursor from the stack.  Popping blindly on an
                # out-of-order close used to evict the still-open top cursor
                # (which then leaked) while leaving this one in the stack,
                # corrupting every subsequent close.
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
        if self._savepoint:
            self._savepoint.close(rollback=self.readonly)
            self._savepoint = None
        self.clear()
        self._now = None  # next simulated transaction gets a fresh timestamp
        self.prerollback.clear()
        self.postrollback.clear()
        self.postcommit.clear()  # TestCursor ignores post-commit hooks by default

    def rollback(self) -> None:
        """Perform an SQL ``ROLLBACK``.

        Not guarded by ``_savepoint_depth`` — see :meth:`commit`.
        """
        self.clear()
        self._now = None  # next simulated transaction gets a fresh timestamp
        self.postcommit.clear()
        self.prerollback.run()
        if self._savepoint:
            self._savepoint.close(rollback=True)
            self._savepoint = None
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
