"""Tier-1 (database-free) tests for :mod:`odoo.db.pool`.

``pool.py`` is the package's largest and most concurrency-sensitive module, and
was previously covered only by the DB-backed integration suite.  Everything here
runs without a server: the pure budget/conninfo helpers, and the bookkeeping
that only needs a stand-in for ``psycopg_pool.ConnectionPool`` (semaphore
accounting on every failure path, idle-pool reaping, stale-credential eviction,
name-based close/drain matching).

Borrow paths that must actually reach a backend live in
``odoo/addons/base/tests/test_db_cursor.py``.
"""

import logging
import os
import threading
import unittest
from time import monotonic
from unittest.mock import patch

import psycopg

from odoo.db.dsn import _normalize_dsn_key
from odoo.db.pool import (
    _DIRECT_CONNECTION,
    _PROBE_CONNECT_TIMEOUT,
    ConnectionBudget,
    ConnectionPool,
    PoolError,
    _base_conn_options,
    _libpq_connect_timeout,
    _remaining,
    _SuppressKnownPoolWarnings,
)
from odoo.db.reaper import _LAST_BORROW_ATTR, note_activity


def _fake_pool_factory(*_a, **_k):
    """Ignore psycopg_pool's real constructor kwargs and hand back a stand-in."""
    return _FakePool()


def _raise(exc):
    """Return a callable that raises *exc* — a stand-in for a failing getconn."""

    def _fn(*a, **k):
        raise exc

    return _fn


class TestBorrowBudgetHelpers(unittest.TestCase):
    """The clamps that keep one ``borrow()`` inside ``db_borrow_timeout``."""

    def test_remaining_is_unbounded_without_a_deadline(self):
        self.assertEqual(_remaining(None), float("inf"))

    def test_remaining_counts_down_and_goes_negative(self):
        self.assertGreater(_remaining(monotonic() + 5), 4)
        self.assertLess(_remaining(monotonic() - 1), 0)

    def test_no_deadline_keeps_the_cap(self):
        self.assertEqual(_libpq_connect_timeout(None, _PROBE_CONNECT_TIMEOUT), 5)

    def test_ample_budget_keeps_the_cap(self):
        self.assertEqual(_libpq_connect_timeout(monotonic() + 60, 5), 5)

    def test_tight_budget_shrinks_below_the_cap(self):
        self.assertEqual(_libpq_connect_timeout(monotonic() + 3.9, 5), 3)

    def test_exhausted_budget_returns_zero_not_a_libpq_forever(self):
        """0 means "skip the connect", never a value to hand libpq.

        libpq reads ``connect_timeout=0``/negative as *wait indefinitely* (and
        silently raises 1 to 2), so returning a sub-second budget verbatim would
        turn the tail of a deadline into an unbounded connect — the overrun this
        helper exists to prevent (borrow measured 13s against a 3s budget).
        """
        for deadline in (monotonic() + 0.9, monotonic(), monotonic() - 10):
            with self.subTest(deadline=deadline):
                self.assertEqual(_libpq_connect_timeout(deadline, 5), 0)


class TestBaseConnOptions(unittest.TestCase):
    """kwarg > URI ``?options=`` > ``PGOPTIONS``, so Odoo extends rather than
    silently replaces whatever GUCs the operator configured."""

    def test_explicit_kwarg_wins(self):
        with patch.dict(os.environ, {"PGOPTIONS": "-c from_env=1"}):
            self.assertEqual(
                _base_conn_options(
                    "postgresql://h/db?options=-c%20from_uri%3D1",
                    {"options": "-c from_kwarg=1"},
                ),
                "-c from_kwarg=1",
            )

    def test_uri_options_beat_the_environment(self):
        with patch.dict(os.environ, {"PGOPTIONS": "-c from_env=1"}):
            self.assertEqual(
                _base_conn_options("postgresql://h/db?options=-c%20from_uri%3D1", {}),
                "-c from_uri=1",
            )

    def test_environment_is_the_last_resort(self):
        with patch.dict(os.environ, {"PGOPTIONS": "-c from_env=1"}):
            self.assertEqual(_base_conn_options("", {}), "-c from_env=1")

    def test_nothing_configured_is_empty(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(_base_conn_options("", {}), "")


class TestSuppressKnownPoolWarnings(unittest.TestCase):
    def _record(self, msg):
        return logging.LogRecord(
            "psycopg.pool", logging.WARNING, __file__, 1, msg, (), None
        )

    def test_expected_noise_is_dropped(self):
        f = _SuppressKnownPoolWarnings()
        self.assertFalse(f.filter(self._record("discarding closed connection: x")))
        self.assertFalse(f.filter(self._record('database "gone" does not exist')))

    def test_real_errors_survive(self):
        f = _SuppressKnownPoolWarnings()
        self.assertTrue(f.filter(self._record('role "nobody" does not exist')))
        self.assertTrue(f.filter(self._record("connection refused")))


class _FakePool:
    """Stand-in for ``psycopg_pool.ConnectionPool`` — no sockets, no threads."""

    def __init__(self, size=1, available=1, closed=False):
        self._stats = {"pool_size": size, "pool_available": available}
        self.closed = closed
        self.close_calls = 0
        self.drain_calls = 0

    def get_stats(self):
        return dict(self._stats)

    def close(self):
        self.close_calls += 1
        self.closed = True

    def drain(self):
        self.drain_calls += 1


def _key(**kw):
    return frozenset(kw.items())


class TestConstructorValidation(unittest.TestCase):
    def test_rejects_non_positive_maxconn(self):
        for bad in (0, -1):
            with self.subTest(maxconn=bad), self.assertRaises(ValueError):
                ConnectionPool(maxconn=bad)

    def test_rejects_negative_minconn(self):
        with self.assertRaises(ValueError):
            ConnectionPool(maxconn=4, minconn=-1)

    def test_rejects_minconn_above_maxconn(self):
        with self.assertRaises(ValueError):
            ConnectionPool(maxconn=2, minconn=3)


class TestSemaphoreAccounting(unittest.TestCase):
    """The permit is taken in ``borrow`` and released exactly once."""

    def test_give_back_of_an_untracked_connection_never_over_releases(self):
        """No ``_odoo_pool`` marker means no permit is held.

        Releasing anyway would over-increment the BoundedSemaphore and inflate
        the budget past ``maxconn`` — a leak that only shows up under load.
        """
        pool = ConnectionPool(maxconn=3)

        class Conn:
            closed = False

            def close(self):
                type(self).closed = True

        conn = Conn()
        pool.give_back(conn)
        self.assertEqual(pool._budget.available, 3)
        self.assertTrue(Conn.closed, "an unowned live connection must be closed")

    def test_direct_connection_release_is_claimed_exactly_once(self):
        """``give_back`` pops the marker atomically, so a double return is a
        no-op rather than a double release."""
        pool = ConnectionPool(maxconn=3)
        pool._budget.acquire(1.0)
        with pool._lock:
            pool._direct_out += 1

        class Conn:
            closed = False

            def __init__(self):
                self._odoo_pool = _DIRECT_CONNECTION

            def close(self):
                self.closed = True

        conn = Conn()
        pool.give_back(conn)
        self.assertEqual(pool._budget.available, 3)
        self.assertEqual(pool._direct_out, 0)
        self.assertTrue(conn.closed, "a maintenance-db connection is never pooled")

        pool.give_back(conn)
        self.assertEqual(pool._budget.available, 3)
        self.assertEqual(pool._direct_out, 0)

    def test_repr_counts_direct_connections(self):
        pool = ConnectionPool(maxconn=8)
        pool._pools = {_key(database="db"): _FakePool(size=3, available=1)}
        pool._direct_out = 2
        text = repr(pool)
        self.assertIn("used=2/total=3/limit=8", text)
        self.assertIn("direct=2", text)


class TestIdlePoolReaping(unittest.TestCase):
    def _pool(self, ttl=300.0):
        return ConnectionPool(maxconn=8, reap_idle_ttl=ttl)

    def test_disabled_when_ttl_is_not_positive(self):
        pool = self._pool(ttl=0)
        pool._pools = {_key(database="db"): _FakePool()}
        setattr(next(iter(pool._pools.values())), _LAST_BORROW_ATTR, monotonic() - 1e6)
        self.assertEqual(pool._reaper.collect(pool._pools), [])

    def test_reaps_only_pools_idle_past_the_ttl(self):
        pool = self._pool(ttl=10)
        fresh, stale = _FakePool(), _FakePool()
        setattr(fresh, _LAST_BORROW_ATTR, monotonic())
        setattr(stale, _LAST_BORROW_ATTR, monotonic() - 60)
        pool._pools = {_key(database="fresh"): fresh, _key(database="stale"): stale}
        self.assertEqual(
            [dict(k)["database"] for k in pool._reaper.collect(pool._pools)],
            ["stale"],
        )

    def test_never_reaps_a_pool_with_a_checked_out_connection(self):
        """A long-lived cron ``LISTEN`` holds a connection while its pool looks
        idle; reaping it would close the connection out from under the holder."""
        pool = self._pool(ttl=10)
        held = _FakePool(size=2, available=1)
        setattr(held, _LAST_BORROW_ATTR, monotonic() - 60)
        pool._pools = {_key(database="held"): held}
        self.assertEqual(pool._reaper.collect(pool._pools), [])

    def test_excluded_key_is_never_reaped(self):
        pool = self._pool(ttl=10)
        k = _key(database="mine")
        p = _FakePool()
        setattr(p, _LAST_BORROW_ATTR, monotonic() - 60)
        pool._pools = {k: p}
        self.assertEqual(pool._reaper.collect(pool._pools, exclude_key=k), [])

    def test_note_pool_activity_protects_a_returned_pool(self):
        """``give_back`` re-stamps the pool, so a connection held longer than the
        TTL and then returned does not leave a stale stamp for the next sweep."""
        pool = self._pool(ttl=10)
        p = _FakePool()
        setattr(p, _LAST_BORROW_ATTR, monotonic() - 60)
        pool._pools = {_key(database="db"): p}
        note_activity(p)
        self.assertEqual(pool._reaper.collect(pool._pools), [])

    def test_reap_check_interval_is_derived_and_floored(self):
        self.assertEqual(
            ConnectionPool(maxconn=4, reap_idle_ttl=400)._reaper.check_interval, 100
        )
        self.assertEqual(
            ConnectionPool(maxconn=4, reap_idle_ttl=0.4)._reaper.check_interval, 1.0
        )
        self.assertEqual(
            ConnectionPool(maxconn=4, reap_idle_ttl=0)._reaper.check_interval, 0.0
        )


class TestCloseAndDrainMatching(unittest.TestCase):
    """``close_db``/``drain_db`` match on the database component alone: the same
    database reached by a URI and by keywords lands in different keys."""

    def _pool_with(self):
        return ConnectionPool(maxconn=8)

    def test_close_database_matches_every_dsn_form(self):
        a, b, other = _FakePool(), _FakePool(), _FakePool()
        cp = self._pool_with()
        cp._pools = {
            _key(database="db", host="h1"): a,
            _key(database="db", host="h2", password_fp="ab"): b,
            _key(database="elsewhere"): other,
        }
        cp.close_database("db")
        self.assertEqual((a.close_calls, b.close_calls, other.close_calls), (1, 1, 0))
        self.assertEqual(list(cp._pools.values()), [other])

    def test_close_all_empties_the_registry(self):
        a, b = _FakePool(), _FakePool()
        cp = self._pool_with()
        cp._pools = {_key(database="a"): a, _key(database="b"): b}
        cp.close_all()
        self.assertEqual(cp._pools, {})
        self.assertTrue(a.close_calls and b.close_calls)

    def test_drain_database_skips_already_closed_pools(self):
        live, dead = _FakePool(), _FakePool(closed=True)
        cp = self._pool_with()
        cp._pools = {
            _key(database="db", host="a"): live,
            _key(database="db", host="b"): dead,
        }
        cp.drain_database("db")
        self.assertEqual((live.drain_calls, dead.drain_calls), (1, 0))

    def test_get_stats_is_keyed_by_database_name(self):
        cp = self._pool_with()
        cp._pools = {_key(database="db"): _FakePool(size=4, available=2)}
        self.assertEqual(cp.get_stats(), {"db": {"pool_size": 4, "pool_available": 2}})

    def test_safe_close_and_drain_swallow_one_pools_failure(self):
        """One pool's teardown must not abort its siblings' — ``close()`` joins
        worker threads and can raise (e.g. at interpreter shutdown)."""

        class Boom(_FakePool):
            def close(self):
                raise RuntimeError("boom")

            def drain(self):
                raise RuntimeError("boom")

        ConnectionPool._safe_close(Boom())
        ConnectionPool._safe_drain(Boom())


class TestPoolErrorIsRaisedForCapacity(unittest.TestCase):
    def test_exhausted_semaphore_reports_the_limit_and_direct_count(self):
        pool = ConnectionPool(maxconn=1, borrow_timeout=0.05)
        pool._budget.acquire(1.0)
        pool._direct_out = 2
        with patch.object(pool, "_get_or_create_pool", return_value=_FakePool()):
            with self.assertRaises(PoolError) as ctx:
                pool.borrow({"dbname": "somedb"})
        msg = str(ctx.exception)
        self.assertIn("connection budget (1)", msg)
        self.assertIn("2 direct maintenance connection(s)", msg)

    def test_borrow_budget_is_taken_before_pool_creation(self):
        """The deadline must cover the cold path's probe, not start after it.

        Regression: ``deadline`` used to be computed *after*
        ``_get_or_create_pool``, so the two 5s probe connects landed on top of
        ``db_borrow_timeout`` (13s measured against a 3s budget).
        """
        pool = ConnectionPool(maxconn=1, borrow_timeout=2.0)
        pool._budget.acquire(1.0)
        seen = {}

        def fake_get_or_create(key, connection_info, deadline=None):
            seen["deadline"] = deadline
            return _FakePool()

        with patch.object(pool, "_get_or_create_pool", fake_get_or_create):
            start = monotonic()
            with self.assertRaises(PoolError):
                pool.borrow({"dbname": "somedb"})
            elapsed = monotonic() - start
        self.assertIsNotNone(
            seen["deadline"], "pool creation must receive the deadline"
        )
        self.assertLessEqual(elapsed, 3.0, "the semaphore wait must use what is left")


class TestConnectionBudgetSharing(unittest.TestCase):
    """``db_maxconn`` must cap the PROCESS, not each pool separately.

    Regression: the R/W and read-only pools each owned a
    ``BoundedSemaphore(db_maxconn)``, so one worker could check out
    ``2 * db_maxconn`` connections — 128 at the default, past a stock
    ``max_connections = 100``.  ``odoo/db/__init__.py`` now builds ONE
    :class:`ConnectionBudget` and hands it to both.
    """

    def test_a_shared_budget_is_consumed_by_both_pools(self):
        budget = ConnectionBudget(2)
        rw = ConnectionPool(maxconn=2, budget=budget)
        ro = ConnectionPool(maxconn=2, readonly=True, budget=budget)
        self.assertIs(rw._budget, ro._budget)
        self.assertFalse(rw.readonly)
        self.assertTrue(ro.readonly)
        self.assertTrue(rw._budget.acquire(0.01))
        self.assertTrue(rw._budget.acquire(0.01))
        self.assertFalse(
            ro._budget.acquire(0.01),
            "a shared budget must not hand out more than maxconn in total",
        )
        rw._budget.release()
        self.assertTrue(ro._budget.acquire(0.01), "a release frees it for either pool")
        ro._budget.release()
        rw._budget.release()

    def test_a_directly_constructed_pool_owns_its_budget(self):
        a, b = ConnectionPool(maxconn=2), ConnectionPool(maxconn=2)
        self.assertIsNot(a._budget, b._budget)
        self.assertTrue(a._budget.acquire(0.01))
        self.assertTrue(a._budget.acquire(0.01))
        self.assertTrue(b._budget.acquire(0.01))
        b._budget.release()
        a._budget.release()
        a._budget.release()

    def test_budget_rejects_a_non_positive_ceiling(self):
        for bad in (0, -1):
            with self.subTest(maxconn=bad), self.assertRaises(ValueError):
                ConnectionBudget(bad)

    def test_saturation_is_bounded_not_a_hang(self):
        """The trade a shared budget makes: two pools CAN starve each other.

        A request holding a R/W cursor while opening a read-only one now
        competes with itself for permits, where two independent budgets could
        not.  That is acceptable only because it degrades on a clock:
        ``db_borrow_timeout`` turns saturation into a ``PoolError``.  Silently
        exceeding the server's ``max_connections`` — what the two-budget
        arrangement did — has no such bound.
        """
        budget = ConnectionBudget(1)
        ro = ConnectionPool(
            maxconn=1, readonly=True, budget=budget, borrow_timeout=0.05
        )
        budget.acquire(0.01)
        started = monotonic()
        with patch.object(ro, "_get_or_create_pool", return_value=_FakePool()):
            with self.assertRaises(PoolError):
                ro.borrow({"dbname": "somedb"})
        self.assertLess(
            monotonic() - started, 2.0, "must fail on the borrow timeout, not hang"
        )
        budget.release()

    def test_double_release_is_loud(self):
        budget = ConnectionBudget(1)
        budget.acquire(0.01)
        budget.release()
        with self.assertRaises(ValueError):
            budget.release()

    def test_note_pool_activity_needs_no_lock(self):
        """``setattr`` is atomic under the GIL; hammer it from many threads."""
        p = _FakePool()
        errors = []

        def spin():
            try:
                for _ in range(2000):
                    note_activity(p)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=spin) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertIsInstance(getattr(p, _LAST_BORROW_ATTR), float)


class TestReachabilityProof(unittest.TestCase):
    """The pre-flight probe must not re-ask a question already answered.

    It costs a full extra connect and exists only to turn a *permanent* connect
    failure into a fast one.  With ``db_pool_reap_idle`` (300s) below
    ``db_conn_max_idle`` (600s), a quiet database is reaped and rebuilt over and
    over, so the probe ran repeatedly against a DSN already known to work.
    """

    def _pool_with_probe_counter(self, **kw):
        pool = ConnectionPool(maxconn=2, **kw)
        calls = []
        pool._probe_connectable = lambda *a, **k: calls.append(a)
        return pool, calls

    def test_first_cold_start_probes(self):
        pool, calls = self._pool_with_probe_counter()
        key = _normalize_dsn_key({"dbname": "d"})
        with patch("odoo.db.pool._PsycopgPool", _fake_pool_factory):
            pool._get_or_create_pool(key, {"dbname": "d"})
        self.assertEqual(len(calls), 1, "an unseen DSN must be probed")

    def test_rebuild_after_a_proven_connect_skips_the_probe(self):
        pool, calls = self._pool_with_probe_counter()
        key = _normalize_dsn_key({"dbname": "d"})
        pool._mark_reachable(key)
        pool._pools.clear()
        with patch("odoo.db.pool._PsycopgPool", _fake_pool_factory):
            pool._get_or_create_pool(key, {"dbname": "d"})
        self.assertEqual(calls, [], "a proven DSN must not be re-probed")

    def test_close_database_revokes_the_proof(self):
        pool, calls = self._pool_with_probe_counter()
        key = _normalize_dsn_key({"dbname": "d"})
        pool._mark_reachable(key)
        pool.close_database("d")
        self.assertFalse(pool._is_proven_reachable(key))
        with patch("odoo.db.pool._PsycopgPool", _fake_pool_factory):
            pool._get_or_create_pool(key, {"dbname": "d"})
        self.assertEqual(len(calls), 1, "a closed database must be probed again")

    def test_close_database_revokes_proofs_with_no_live_pool(self):
        pool, _ = self._pool_with_probe_counter()
        key = _normalize_dsn_key({"dbname": "d", "host": "h"})
        pool._mark_reachable(key)
        self.assertEqual(pool._pools, {})
        pool.close_database("d")
        self.assertFalse(pool._is_proven_reachable(key))

    def test_other_databases_keep_their_proof(self):
        pool, _ = self._pool_with_probe_counter()
        keep = _normalize_dsn_key({"dbname": "other"})
        pool._mark_reachable(keep)
        pool._mark_reachable(_normalize_dsn_key({"dbname": "d"}))
        pool.close_database("d")
        self.assertTrue(pool._is_proven_reachable(keep))

    def test_a_connect_failure_revokes_the_proof(self):
        """A target that stops answering must become fast-failing again."""
        pool = ConnectionPool(maxconn=2, borrow_timeout=0.05)
        key = _normalize_dsn_key({"dbname": "d"})
        pool._mark_reachable(key)
        failing = _FakePool()
        failing.getconn = _raise(psycopg.errors.InvalidCatalogName("gone"))
        with self.assertRaises(psycopg.Error):
            pool._getconn_with_retry(failing, key, {"dbname": "d"}, monotonic() + 0.05)
        self.assertFalse(pool._is_proven_reachable(key))

    def test_rotated_credentials_revoke_the_old_proof(self):
        """A stale-credential eviction voids the evicted key, not the new one."""
        pool, _ = self._pool_with_probe_counter()
        old = _normalize_dsn_key({"dbname": "d", "password": "old"})
        new = _normalize_dsn_key({"dbname": "d", "password": "new"})
        pool._mark_reachable(old)
        pool._pools[old] = _FakePool()
        with patch("odoo.db.pool._PsycopgPool", _fake_pool_factory):
            pool._get_or_create_pool(new, {"dbname": "d", "password": "new"})
        self.assertFalse(pool._is_proven_reachable(old))


if __name__ == "__main__":
    unittest.main()
