import threading
import time
from unittest.mock import Mock

from odoo.tests.common import BaseCase

from odoo.addons.credential.tools import connection_manager
from odoo.addons.credential.tools.connection_manager import (
    ConnectionManager,
    get_connection_manager,
)


class MockConnection:
    def __init__(self, name):
        self.name = name
        self.disconnected = False
        self.closed = False

    def disconnect(self):
        self.disconnected = True

    def close(self):
        self.closed = True


class TestConnectionManager(BaseCase):
    def setUp(self):
        super().setUp()
        self.manager = ConnectionManager(max_connections=3)

    def test_init(self):
        manager = ConnectionManager(max_connections=10)
        self.assertEqual(manager._max_size, 10)
        self.assertEqual(len(manager._cache), 0)

    def test_set_and_get(self):
        conn = MockConnection("test1")
        self.manager.set("key1", conn)

        retrieved = self.manager.get("key1")
        self.assertEqual(retrieved, conn)
        self.assertEqual(retrieved.name, "test1")

    def test_get_nonexistent(self):
        result = self.manager.get("nonexistent")
        self.assertIsNone(result)

    def test_set_with_metadata(self):
        conn = MockConnection("test1")
        metadata = {"protocol": "mqtt", "device": "sensor-001"}

        self.manager.set("key1", conn, metadata=metadata)
        meta = self.manager.get_metadata("key1")

        self.assertIsNotNone(meta)
        self.assertEqual(meta["metadata"]["protocol"], "mqtt")
        self.assertEqual(meta["metadata"]["device"], "sensor-001")
        self.assertIn("created_at", meta)
        self.assertIn("last_used", meta)

    def test_get_updates_last_used(self):
        conn = MockConnection("test1")
        self.manager.set("key1", conn)

        meta1 = self.manager.get_metadata("key1")
        time.sleep(1.1)
        self.manager.get("key1")
        meta2 = self.manager.get_metadata("key1")

        self.assertGreater(meta2["last_used"], meta1["last_used"])

    def test_lru_eviction(self):
        conn1 = MockConnection("conn1")
        conn2 = MockConnection("conn2")
        conn3 = MockConnection("conn3")
        conn4 = MockConnection("conn4")

        self.manager.set("key1", conn1)
        self.manager.set("key2", conn2)
        self.manager.set("key3", conn3)

        self.manager.set("key4", conn4)

        self.assertIsNone(self.manager.get("key1"))
        self.assertTrue(conn1.disconnected or conn1.closed)

        self.assertIsNotNone(self.manager.get("key2"))
        self.assertIsNotNone(self.manager.get("key3"))
        self.assertIsNotNone(self.manager.get("key4"))

    def test_lru_order_preserved(self):
        conn1 = MockConnection("conn1")
        conn2 = MockConnection("conn2")
        conn3 = MockConnection("conn3")
        conn4 = MockConnection("conn4")

        self.manager.set("key1", conn1)
        self.manager.set("key2", conn2)
        self.manager.set("key3", conn3)

        self.manager.get("key1")

        self.manager.set("key4", conn4)

        self.assertIsNotNone(self.manager.get("key1"))

        self.assertIsNone(self.manager.get("key2"))

    def test_remove_connection(self):
        conn = MockConnection("test1")
        self.manager.set("key1", conn)

        result = self.manager.invalidate("key1")

        self.assertTrue(result)
        self.assertIsNone(self.manager.get("key1"))
        self.assertTrue(conn.disconnected or conn.closed)

    def test_remove_nonexistent(self):
        result = self.manager.invalidate("nonexistent")
        self.assertFalse(result)

    def test_keys(self):
        conn1 = MockConnection("conn1")
        conn2 = MockConnection("conn2")

        self.manager.set("key1", conn1)
        self.manager.set("key2", conn2)

        keys = self.manager.keys()

        self.assertEqual(len(keys), 2)
        self.assertIn("key1", keys)
        self.assertIn("key2", keys)

    def test_get_stats(self):
        conn1 = MockConnection("conn1")
        conn2 = MockConnection("conn2")

        self.manager.set("key1", conn1)
        self.manager.set("key2", conn2)

        stats = self.manager.get_stats()

        self.assertEqual(stats["size"], 2)
        self.assertEqual(stats["max_size"], 3)

    def test_invalidate_all(self):
        conn1 = MockConnection("conn1")
        conn2 = MockConnection("conn2")

        self.manager.set("key1", conn1)
        self.manager.set("key2", conn2)

        self.manager.invalidate_all()

        self.assertEqual(len(self.manager.keys()), 0)
        self.assertTrue(conn1.disconnected or conn1.closed)
        self.assertTrue(conn2.disconnected or conn2.closed)

    def test_cleanup_connection_methods(self):

        class ConnWithDisconnect:
            def __init__(self):
                self.disconnected = False

            def disconnect(self):
                self.disconnected = True

        class ConnWithClose:
            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True

        conn1 = ConnWithDisconnect()
        self.manager._cleanup_connection(conn1)
        self.assertTrue(conn1.disconnected)

        conn2 = ConnWithClose()
        self.manager._cleanup_connection(conn2)
        self.assertTrue(conn2.closed)

    def test_thread_safety(self):
        results = []
        errors = []

        def worker(thread_id):
            try:
                for i in range(10):
                    conn = MockConnection(f"conn-{thread_id}-{i}")
                    key = f"key-{thread_id}-{i}"
                    self.manager.set(key, conn)
                    retrieved = self.manager.get(key)
                    if retrieved:
                        results.append((thread_id, i))
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(5):
            thread = threading.Thread(target=worker, args=(i,))
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        self.assertEqual(len(errors), 0)
        self.assertGreater(len(results), 0)

    def test_update_existing_connection(self):
        conn1 = MockConnection("conn1")
        conn2 = MockConnection("conn2")

        self.manager.set("key1", conn1)
        self.manager.set("key1", conn2)

        retrieved = self.manager.get("key1")
        self.assertEqual(retrieved, conn2)
        self.assertEqual(retrieved.name, "conn2")

    def test_get_metadata_nonexistent(self):
        meta = self.manager.get_metadata("nonexistent")
        self.assertIsNone(meta)

    def test_cleanup_stops_background_loop(self):
        class PahoLikeClient:
            def __init__(self):
                self.calls = []

            def loop_stop(self):
                self.calls.append("loop_stop")

            def disconnect(self):
                self.calls.append("disconnect")

        conn = PahoLikeClient()
        self.manager._cleanup_connection(conn)

        self.assertEqual(conn.calls, ["loop_stop", "disconnect"])

    def test_cleanup_none_connection(self):
        self.manager._cleanup_connection(None)

    def test_cleanup_connection_without_methods(self):

        class SimpleConnection:
            pass

        conn = SimpleConnection()
        self.manager._cleanup_connection(conn)


class TestConnectionManagerRegistry(BaseCase):
    def setUp(self):
        super().setUp()
        connection_manager._managers.clear()
        self.addCleanup(connection_manager._managers.clear)

    def test_get_connection_manager_creates_new(self):
        env = Mock()
        env.cr.dbname = "test_db"

        manager = get_connection_manager(env)

        self.assertIsNotNone(manager)
        self.assertIsInstance(manager, ConnectionManager)

    def test_get_connection_manager_returns_existing(self):
        env = Mock()
        env.cr.dbname = "test_db"

        manager1 = get_connection_manager(env)

        manager2 = get_connection_manager(env)

        self.assertIs(manager1, manager2)

    def test_manager_is_isolated_per_database(self):
        env_a, env_b = Mock(), Mock()
        env_a.cr.dbname = "db_a"
        env_b.cr.dbname = "db_b"

        self.assertIsNot(get_connection_manager(env_a), get_connection_manager(env_b))

    def test_manager_survives_registry_rebuild(self):
        env = Mock()
        env.cr.dbname = "test_db"
        manager = get_connection_manager(env)
        conn = MockConnection("device:1")
        manager.set("device:1", conn)

        env.registry = Mock()

        self.assertIs(get_connection_manager(env), manager)
        self.assertIs(get_connection_manager(env).get("device:1"), conn)
        self.assertFalse(conn.disconnected)

    def test_different_max_connections(self):
        env = Mock()
        env.cr.dbname = "test_db"

        manager = get_connection_manager(env, max_connections=500)

        self.assertEqual(manager._max_size, 500)
