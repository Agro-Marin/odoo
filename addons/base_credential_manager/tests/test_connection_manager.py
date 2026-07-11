"""Tests for ConnectionManager functionality."""

import threading
import time
from unittest.mock import Mock

from odoo.tests.common import BaseCase

from odoo.addons.base_credential_manager.tools.connection_manager import (
    ConnectionManager,
    get_connection_manager,
)


class MockConnection:
    """Mock connection object for testing."""

    def __init__(self, name):
        """Initialize mock connection."""
        self.name = name
        self.disconnected = False
        self.closed = False

    def disconnect(self):
        """Mock disconnect method."""
        self.disconnected = True

    def close(self):
        """Mock close method."""
        self.closed = True


class TestConnectionManager(BaseCase):
    """Test ConnectionManager functionality."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()
        self.manager = ConnectionManager(max_connections=3)

    def test_init(self):
        """Test ConnectionManager initialization."""
        manager = ConnectionManager(max_connections=10)
        self.assertEqual(manager._max_size, 10)
        self.assertEqual(len(manager._cache), 0)

    def test_set_and_get(self):
        """Test basic set and get operations."""
        conn = MockConnection("test1")
        self.manager.set(None, "key1", conn)

        retrieved = self.manager.get(None, "key1")
        self.assertEqual(retrieved, conn)
        self.assertEqual(retrieved.name, "test1")

    def test_get_nonexistent(self):
        """Test getting non-existent connection returns None."""
        result = self.manager.get(None, "nonexistent")
        self.assertIsNone(result)

    def test_set_with_metadata(self):
        """Test storing connection with metadata."""
        conn = MockConnection("test1")
        metadata = {"protocol": "mqtt", "device": "sensor-001"}

        self.manager.set(None, "key1", conn, metadata=metadata)
        meta = self.manager.get_metadata(None, "key1")

        self.assertIsNotNone(meta)
        self.assertEqual(meta["metadata"]["protocol"], "mqtt")
        self.assertEqual(meta["metadata"]["device"], "sensor-001")
        self.assertIn("created_at", meta)
        self.assertIn("last_used", meta)

    def test_get_updates_last_used(self):
        """Test that get() updates last_used timestamp."""
        conn = MockConnection("test1")
        self.manager.set(None, "key1", conn)

        meta1 = self.manager.get_metadata(None, "key1")
        # Must exceed 1s: Odoo's fields.Datetime.now() strips microseconds,
        # so a 10ms sleep can leave both timestamps equal at second precision.
        time.sleep(1.1)
        self.manager.get(None, "key1")
        meta2 = self.manager.get_metadata(None, "key1")

        self.assertGreater(meta2["last_used"], meta1["last_used"])

    def test_lru_eviction(self):
        """Test LRU eviction when max connections reached."""
        conn1 = MockConnection("conn1")
        conn2 = MockConnection("conn2")
        conn3 = MockConnection("conn3")
        conn4 = MockConnection("conn4")

        # Fill to capacity (max=3)
        self.manager.set(None, "key1", conn1)
        self.manager.set(None, "key2", conn2)
        self.manager.set(None, "key3", conn3)

        # Add one more - should evict key1 (oldest)
        self.manager.set(None, "key4", conn4)

        # key1 should be evicted and cleaned up
        self.assertIsNone(self.manager.get(None, "key1"))
        self.assertTrue(conn1.disconnected or conn1.closed)

        # Others should still exist
        self.assertIsNotNone(self.manager.get(None, "key2"))
        self.assertIsNotNone(self.manager.get(None, "key3"))
        self.assertIsNotNone(self.manager.get(None, "key4"))

    def test_lru_order_preserved(self):
        """Test that LRU order is maintained correctly."""
        conn1 = MockConnection("conn1")
        conn2 = MockConnection("conn2")
        conn3 = MockConnection("conn3")
        conn4 = MockConnection("conn4")

        # Fill to capacity
        self.manager.set(None, "key1", conn1)
        self.manager.set(None, "key2", conn2)
        self.manager.set(None, "key3", conn3)

        # Access key1 (moves to end)
        self.manager.get(None, "key1")

        # Add key4 - should evict key2 (now oldest)
        self.manager.set(None, "key4", conn4)

        # key1 should still exist (was accessed)
        self.assertIsNotNone(self.manager.get(None, "key1"))

        # key2 should be evicted
        self.assertIsNone(self.manager.get(None, "key2"))

    def test_remove_connection(self):
        """Test removing a connection."""
        conn = MockConnection("test1")
        self.manager.set(None, "key1", conn)

        result = self.manager.remove(None, "key1")

        self.assertTrue(result)
        self.assertIsNone(self.manager.get(None, "key1"))
        self.assertTrue(conn.disconnected or conn.closed)

    def test_remove_nonexistent(self):
        """Test removing non-existent connection returns False."""
        result = self.manager.remove(None, "nonexistent")
        self.assertFalse(result)

    def test_list_connections(self):
        """Test listing all connection keys."""
        conn1 = MockConnection("conn1")
        conn2 = MockConnection("conn2")

        self.manager.set(None, "key1", conn1)
        self.manager.set(None, "key2", conn2)

        keys = self.manager.list_connections(None)

        self.assertEqual(len(keys), 2)
        self.assertIn("key1", keys)
        self.assertIn("key2", keys)

    def test_get_stats(self):
        """Test getting connection statistics."""
        conn1 = MockConnection("conn1")
        conn2 = MockConnection("conn2")

        self.manager.set(None, "key1", conn1)
        self.manager.set(None, "key2", conn2)

        stats = self.manager.get_stats(None)

        self.assertEqual(stats["total_connections"], 2)
        self.assertEqual(stats["max_connections"], 3)

    def test_invalidate_all(self):
        """Test invalidating all connections."""
        conn1 = MockConnection("conn1")
        conn2 = MockConnection("conn2")

        self.manager.set(None, "key1", conn1)
        self.manager.set(None, "key2", conn2)

        self.manager.invalidate_all()

        self.assertEqual(len(self.manager.list_connections()), 0)
        self.assertTrue(conn1.disconnected or conn1.closed)
        self.assertTrue(conn2.disconnected or conn2.closed)

    def test_cleanup_connection_methods(self):
        """Test that cleanup tries multiple disconnect methods."""

        # Mock with disconnect method
        class ConnWithDisconnect:
            def __init__(self):
                self.disconnected = False

            def disconnect(self):
                self.disconnected = True

        # Mock with close method
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
        """Test concurrent set/get operations are thread-safe."""
        results = []
        errors = []

        def worker(thread_id):
            try:
                for i in range(10):
                    conn = MockConnection(f"conn-{thread_id}-{i}")
                    key = f"key-{thread_id}-{i}"
                    self.manager.set(None, key, conn)
                    retrieved = self.manager.get(None, key)
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

        # No errors should occur
        self.assertEqual(len(errors), 0)
        # Some results should be recorded (not all due to LRU eviction)
        self.assertGreater(len(results), 0)

    def test_update_existing_connection(self):
        """Test updating an existing connection key."""
        conn1 = MockConnection("conn1")
        conn2 = MockConnection("conn2")

        self.manager.set(None, "key1", conn1)
        self.manager.set(None, "key1", conn2)  # Update

        retrieved = self.manager.get(None, "key1")
        self.assertEqual(retrieved, conn2)
        self.assertEqual(retrieved.name, "conn2")

    def test_get_metadata_nonexistent(self):
        """Test getting metadata for non-existent connection."""
        meta = self.manager.get_metadata(None, "nonexistent")
        self.assertIsNone(meta)

    def test_cleanup_none_connection(self):
        """Test cleanup handles None connection gracefully."""
        # Should not raise exception
        self.manager._cleanup_connection(None)

    def test_cleanup_connection_without_methods(self):
        """Test cleanup handles connections without disconnect/close methods."""

        class SimpleConnection:
            pass

        conn = SimpleConnection()
        # Should not raise exception
        self.manager._cleanup_connection(conn)


class TestConnectionManagerRegistry(BaseCase):
    """Test registry-based connection manager functionality."""

    def test_get_connection_manager_creates_new(self):
        """Test that get_connection_manager creates manager if not exists."""
        # Mock environment with registry
        env = Mock()
        env.registry = Mock()
        env.cr.dbname = "test_db"

        # No manager exists yet
        del env.registry._connection_manager

        manager = get_connection_manager(env)

        self.assertIsNotNone(manager)
        self.assertIsInstance(manager, ConnectionManager)
        self.assertTrue(hasattr(env.registry, "_connection_manager"))

    def test_get_connection_manager_returns_existing(self):
        """Test that get_connection_manager returns existing manager."""
        env = Mock()
        env.registry = Mock()
        env.cr.dbname = "test_db"

        # Create first manager
        manager1 = get_connection_manager(env)

        # Get again - should return same instance
        manager2 = get_connection_manager(env)

        self.assertIs(manager1, manager2)

    def test_different_max_connections(self):
        """Test creating manager with different max_connections."""
        env = Mock()
        env.registry = Mock()
        env.cr.dbname = "test_db"
        del env.registry._connection_manager

        manager = get_connection_manager(env, max_connections=500)

        self.assertEqual(manager._max_size, 500)
