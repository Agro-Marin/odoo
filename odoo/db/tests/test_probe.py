import unittest
from time import monotonic
from unittest.mock import patch

import psycopg

from odoo.db.dsn import _normalize_dsn_key
from odoo.db.pool import ConnectionPool


class _FakePool:
    def __init__(self, size=1, available=1, closed=False, getconn_raises=None):
        self._stats = {"pool_size": size, "pool_available": available}
        self.closed = closed
        self.close_calls = 0
        self.drain_calls = 0
        self._getconn_raises = getconn_raises

    def get_stats(self):
        return dict(self._stats)

    def getconn(self, timeout=None):
        if self._getconn_raises is not None:
            raise self._getconn_raises
        raise NotImplementedError("this test needs _FakePool(getconn_raises=...)")

    def close(self):
        self.close_calls += 1
        self.closed = True

    def drain(self):
        self.drain_calls += 1


def _fake_pool_factory(*_a, **_k):
    return _FakePool()


class TestReachabilityProof(unittest.TestCase):
    def _pool_with_probe_counter(self, **kw):
        pool = ConnectionPool(maxconn=2, **kw)
        calls = []
        pool._probe.probe_connectable = lambda *a, **k: calls.append(a)  # type: ignore[method-assign]
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
        pool._probe.mark_proven(key)
        pool._pools.clear()
        with patch("odoo.db.pool._PsycopgPool", _fake_pool_factory):
            pool._get_or_create_pool(key, {"dbname": "d"})
        self.assertEqual(calls, [], "a proven DSN must not be re-probed")

    def test_close_database_revokes_the_proof(self):
        pool, calls = self._pool_with_probe_counter()
        key = _normalize_dsn_key({"dbname": "d"})
        pool._probe.mark_proven(key)
        pool.close_database("d")
        self.assertFalse(pool._probe.is_proven(key))
        with patch("odoo.db.pool._PsycopgPool", _fake_pool_factory):
            pool._get_or_create_pool(key, {"dbname": "d"})
        self.assertEqual(len(calls), 1, "a closed database must be probed again")

    def test_close_database_revokes_proofs_with_no_live_pool(self):
        pool, _ = self._pool_with_probe_counter()
        key = _normalize_dsn_key({"dbname": "d", "host": "h"})
        pool._probe.mark_proven(key)
        self.assertEqual(pool._pools, {})
        pool.close_database("d")
        self.assertFalse(pool._probe.is_proven(key))

    def test_other_databases_keep_their_proof(self):
        pool, _ = self._pool_with_probe_counter()
        keep = _normalize_dsn_key({"dbname": "other"})
        pool._probe.mark_proven(keep)
        pool._probe.mark_proven(_normalize_dsn_key({"dbname": "d"}))
        pool.close_database("d")
        self.assertTrue(pool._probe.is_proven(keep))

    def test_a_connect_failure_revokes_the_proof(self):
        pool = ConnectionPool(maxconn=2, borrow_timeout=0.05)
        key = _normalize_dsn_key({"dbname": "d"})
        pool._probe.mark_proven(key)
        failing = _FakePool(getconn_raises=psycopg.errors.InvalidCatalogName("gone"))
        with self.assertRaises(psycopg.Error):
            pool._getconn_with_retry(failing, key, {"dbname": "d"}, monotonic() + 0.05)
        self.assertFalse(pool._probe.is_proven(key))

    def test_rotated_credentials_revoke_the_old_proof(self):
        pool, _ = self._pool_with_probe_counter()
        old = _normalize_dsn_key({"dbname": "d", "password": "old"})
        new = _normalize_dsn_key({"dbname": "d", "password": "new"})
        pool._probe.mark_proven(old)
        pool._pools[old] = _FakePool()
        with patch("odoo.db.pool._PsycopgPool", _fake_pool_factory):
            pool._get_or_create_pool(new, {"dbname": "d", "password": "new"})
        self.assertFalse(pool._probe.is_proven(old))


class TestTheDedupedProbeDoesNotShareATraceback(unittest.TestCase):
    def _run(self, followers=8):
        import threading
        import time

        pool = ConnectionPool(maxconn=8)
        key = _normalize_dsn_key({"dbname": "unreachable"})
        go = threading.Event()
        caught: dict = {}

        def slow_failing_probe(*_a, **_k):
            go.wait(20)
            raise RuntimeError("unreachable host")

        pool._probe.probe_connectable = slow_failing_probe  # type: ignore[method-assign]

        def call(tag):
            try:
                pool._probe.check_connectable(key, "", {})
            except Exception as exc:
                caught[tag] = exc

        leader = threading.Thread(target=call, args=("leader",), daemon=True)
        leader.start()
        time.sleep(0.2)
        threads = [
            threading.Thread(target=call, args=(i,), daemon=True)
            for i in range(followers)
        ]
        for t in threads:
            t.start()
        time.sleep(0.2)
        go.set()
        leader.join(20)
        for t in threads:
            t.join(20)
        return caught

    @staticmethod
    def _frames(exc):
        n, tb = 0, exc.__traceback__
        while tb is not None:
            n += 1
            tb = tb.tb_next
        return n

    def test_every_follower_still_gets_the_leaders_failure(self):
        caught = self._run()
        self.assertEqual(len(caught), 9, "leader plus every follower must raise")
        self.assertTrue(all(isinstance(e, RuntimeError) for e in caught.values()))

    def test_the_shared_traceback_does_not_grow_with_the_followers(self):
        few = self._run(followers=2)
        many = self._run(followers=8)
        self.assertEqual(
            self._frames(few["leader"]),
            self._frames(many["leader"]),
            "the traceback grew with the number of waiters: each follower "
            "raises the same object and a raise appends to it, so a dead DSN "
            "under load produced a stack of repeated frames from unrelated "
            "threads, each keeping its thread's locals alive",
        )


if __name__ == "__main__":
    unittest.main()
