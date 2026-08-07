import unittest
from time import monotonic
from unittest.mock import patch

from odoo.db import lifecycle
from odoo.db.lifecycle import (
    _IDLE_SINCE_ATTR,
    _PREPARE_THRESHOLD,
    _PREPARED_MAX,
    _RESET_SESSION_STATE_SQL,
    _check_connection,
    _configure_connection,
    _reset_connection,
)


class _FakePrepared:
    def __init__(self):
        self.cleared = 0

    def clear(self):
        self.cleared += 1


class _FakeConn:
    def __init__(self):
        self.executed: list[tuple[str, dict]] = []
        self.autocommit = False
        self.isolation_level = "SOMETHING"
        self.read_only = True
        self.prepare_threshold = None
        self.prepared_max = None
        self.adapters = self
        self.registered: list[str] = []
        self._prepared = _FakePrepared()

    def register_loader(self, name, loader):
        self.registered.append(name)

    def execute(self, sql, *, prepare=None):
        self.executed.append((sql, {"prepare": prepare}))


class TestConfigureConnection(unittest.TestCase):
    def test_registers_adapters_and_prepare_tuning(self):
        conn = _FakeConn()
        _configure_connection(conn)
        self.assertIn("numeric", conn.registered)
        self.assertEqual(conn.prepare_threshold, _PREPARE_THRESHOLD)
        self.assertEqual(conn.prepared_max, _PREPARED_MAX)

    def test_seeds_the_liveness_stamp(self):
        conn = _FakeConn()
        _configure_connection(conn)
        self.assertIsNotNone(getattr(conn, _IDLE_SINCE_ATTR, None))

    def test_runs_no_statement(self):
        conn = _FakeConn()
        _configure_connection(conn)
        self.assertEqual(conn.executed, [])


class TestResetSessionStateSql(unittest.TestCase):
    def test_closes_every_documented_leak(self):
        for clause in (
            "RESET ALL",
            "RESET SESSION AUTHORIZATION",
            "CLOSE ALL",
            "UNLISTEN *",
            "pg_advisory_unlock_all()",
            "DISCARD TEMP",
            "DISCARD SEQUENCES",
        ):
            with self.subTest(clause=clause):
                self.assertIn(clause, _RESET_SESSION_STATE_SQL)

    def test_spares_the_caches_it_means_to_spare(self):
        self.assertNotIn("DEALLOCATE", _RESET_SESSION_STATE_SQL)
        self.assertNotIn("DISCARD PLANS", _RESET_SESSION_STATE_SQL)
        self.assertNotIn("DISCARD ALL", _RESET_SESSION_STATE_SQL)

    def test_is_a_single_round_trip(self):
        self.assertEqual(_RESET_SESSION_STATE_SQL.count(";"), 6)


class TestResetConnection(unittest.TestCase):
    def _reset(self, discard):
        conn = _FakeConn()
        with patch.object(lifecycle.tools, "config", {"db_discard_on_return": discard}):
            _reset_connection(conn)
        return conn

    def test_default_uses_the_cheap_reset(self):
        conn = self._reset(False)
        self.assertEqual([sql for sql, _ in conn.executed], [_RESET_SESSION_STATE_SQL])

    def test_discard_on_return_uses_discard_all(self):
        conn = self._reset(True)
        self.assertEqual([sql for sql, _ in conn.executed], ["DISCARD ALL"])

    def test_discard_all_also_drops_the_client_side_prepare_cache(self):
        conn = self._reset(True)
        self.assertEqual(conn._prepared.cleared, 1)

    def test_cheap_reset_keeps_the_client_side_prepare_cache(self):
        conn = self._reset(False)
        self.assertEqual(conn._prepared.cleared, 0)

    def test_never_auto_prepares_the_reset_itself(self):
        for discard in (False, True):
            with self.subTest(discard=discard):
                conn = self._reset(discard)
                self.assertEqual([kw["prepare"] for _, kw in conn.executed], [False])

    def test_restores_session_defaults_and_prepare_tuning(self):
        conn = self._reset(False)
        self.assertFalse(conn.autocommit, "must leave autocommit off for the next tx")
        self.assertIsNone(conn.isolation_level, "server default")
        self.assertIsNone(conn.read_only, "server default")
        self.assertEqual(conn.prepare_threshold, _PREPARE_THRESHOLD)
        self.assertEqual(conn.prepared_max, _PREPARED_MAX)

    def test_restamps_liveness_last(self):
        conn = self._reset(False)
        self.assertIsNotNone(getattr(conn, _IDLE_SINCE_ATTR, None))


class TestCheckConnection(unittest.TestCase):
    GRACE = 1.0

    def setUp(self):
        self.probed: list[object] = []

        def _record(conn):
            self.probed.append(conn)

        patcher = patch("odoo.db.lifecycle._PsycopgPool.check_connection", _record)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _check(self, conn, grace=GRACE):
        with patch.object(lifecycle.tools, "config", {"db_healthcheck_grace": grace}):
            _check_connection(conn)

    def test_recently_released_connection_skips_the_probe(self):
        conn = _FakeConn()
        setattr(conn, _IDLE_SINCE_ATTR, monotonic())
        self._check(conn)
        self.assertEqual(self.probed, [], "a just-released connection was alive")

    def test_connection_idle_past_the_window_is_probed(self):
        conn = _FakeConn()
        setattr(conn, _IDLE_SINCE_ATTR, monotonic() - (self.GRACE + 1))
        self._check(conn)
        self.assertEqual(self.probed, [conn])

    def test_unstamped_connection_fails_safe_to_the_probe(self):
        conn = _FakeConn()
        self._check(conn)
        self.assertEqual(self.probed, [conn], "unknown liveness must be verified")

    def test_zero_grace_probes_every_borrow(self):
        conn = _FakeConn()
        setattr(conn, _IDLE_SINCE_ATTR, monotonic())
        self._check(conn, grace=0)
        self.assertEqual(self.probed, [conn], "grace 0 must disable the window")

    def test_a_wider_grace_spares_a_longer_idle_connection(self):
        conn = _FakeConn()
        setattr(conn, _IDLE_SINCE_ATTR, monotonic() - 30)
        self._check(conn, grace=60)
        self.assertEqual(self.probed, [])


if __name__ == "__main__":
    unittest.main()
