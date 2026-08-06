"""The process-wide cap on checked-out connections.

Split out of :mod:`odoo.db.pool` because it is pure, self-contained policy —
one semaphore and its accounting — that both the R/W and the read-only
:class:`~odoo.db.pool.ConnectionPool` share, and that the permit-accounting
tests exercise without a pool, a socket, or a database.
"""

from __future__ import annotations

import threading


class ConnectionBudget:
    """The cap on connections checked out at once, shareable between pools.

    ``db_maxconn`` is documented as "the maximum number of physical connections
    to PostgreSQL", and that is what an operator sizes ``max_connections``
    against.  It used to mean something else: the R/W and read-only pools are
    two ``ConnectionPool`` instances, each of which owned a
    ``BoundedSemaphore(db_maxconn)``, so a single worker process could hold
    ``2 * db_maxconn`` connections — 128 against the default 64, which alone
    exceeds a stock ``max_connections = 100``.  Hoisting the semaphore into one
    object that both pools share makes the option mean what it says.

    Note the trade this makes explicit.  Two independent budgets could never
    starve each other; one shared budget can, and a request holding a R/W cursor
    while opening a read-only one (nested cursors are an ordinary Odoo pattern)
    now competes with itself for the same permits.  That is not a new failure
    mode — two cursors from the *same* pool always did — and it is bounded:
    ``db_borrow_timeout`` turns saturation into a ``PoolError`` after 30s rather
    than a permanent hang.  The alternative, silently exceeding the server's
    connection limit, fails harder and less legibly.

    That trade is only defensible if saturation is *visible* before it bites, so
    the budget counts its own exhaustions and publishes :attr:`available`; both
    surface through ``ConnectionPool.health()``.  The counter lives here rather
    than on either pool's :class:`~odoo.db.stats.PoolStats` because one budget
    is shared by both — an exhaustion belongs to the budget, not to whichever
    pool happened to ask last.
    """

    __slots__ = ("_sem", "exhausted", "maxconn")

    def __init__(self, maxconn: int):
        if maxconn <= 0:
            raise ValueError(f"ConnectionBudget maxconn must be >= 1, got {maxconn}")
        self.maxconn = maxconn
        self._sem = threading.BoundedSemaphore(maxconn)
        self.exhausted = 0

    def acquire(self, timeout: float) -> bool:
        """Take one permit, waiting at most *timeout* seconds.

        A non-finite *timeout* (``float("inf")``, from a caller with no
        deadline, e.g. ``ConnectionPool._borrow_direct(deadline=None)``) waits
        indefinitely: it must not reach ``BoundedSemaphore.acquire``, whose
        deadline arithmetic raises ``OverflowError`` the moment the semaphore
        actually has to wait — a saturation-only crash that no fast path ever
        exercises.
        """
        if timeout == float("inf"):
            got = self._sem.acquire()
        else:
            got = self._sem.acquire(timeout=max(0.0, timeout))
        if not got:
            self.exhausted += 1
        return got

    def release(self) -> None:
        """Return one permit.  Raises ``ValueError`` on a double release —
        the bounded semaphore is what makes permit-accounting bugs loud."""
        self._sem.release()

    @property
    def available(self) -> int:
        """Permits not currently held — a racy snapshot, for diagnostics only.

        Exposed so callers (the tests that pin permit accounting on every
        failure path, and anything reporting pool health) read one documented
        attribute instead of reaching into ``threading.BoundedSemaphore``'s
        private ``_value``.  Never branch on it: it can change between the read
        and the next statement; take a permit with :meth:`acquire` instead.
        """
        return self._sem._value

    @property
    def in_use(self) -> int:
        """Permits currently held — a racy snapshot, for diagnostics only."""
        return self.maxconn - self._sem._value
