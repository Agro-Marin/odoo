import time

from odoo.tests.common import BaseCase

from odoo.addons.base_credential_manager.tools import SessionCache


class TestSessionCache(BaseCase):
    """Test session caching functionality."""

    def setUp(self):
        super().setUp()
        self.cache = SessionCache(max_size=3, ttl_hours=0.001)  # 3.6 seconds TTL

    def test_cache_set_get(self):
        """Test basic cache set and get."""
        self.cache.set("key1", "value1")
        result = self.cache.get("key1")

        self.assertEqual(result, "value1")

    def test_cache_miss(self):
        """Test cache miss returns None."""
        result = self.cache.get("nonexistent")

        self.assertIsNone(result)

    def test_cache_expiration(self):
        """Test that cached items expire after TTL."""
        self.cache.set("key1", "value1")

        # Wait for expiration
        time.sleep(4)  # > 3.6 seconds

        result = self.cache.get("key1")

        self.assertIsNone(result)

    def test_cache_lru_eviction(self):
        """Test LRU eviction when max size reached."""
        # Fill cache to max
        self.cache.set("key1", "value1")
        self.cache.set("key2", "value2")
        self.cache.set("key3", "value3")

        # Add one more (should evict key1)
        self.cache.set("key4", "value4")

        # key1 should be evicted
        self.assertIsNone(self.cache.get("key1"))

        # Others should still exist
        self.assertEqual(self.cache.get("key2"), "value2")
        self.assertEqual(self.cache.get("key3"), "value3")
        self.assertEqual(self.cache.get("key4"), "value4")

    def test_cache_lru_order(self):
        """Test that recently used items are not evicted."""
        self.cache.set("key1", "value1")
        self.cache.set("key2", "value2")
        self.cache.set("key3", "value3")

        # Access key1 (moves to end)
        self.cache.get("key1")

        # Add key4 (should evict key2, not key1)
        self.cache.set("key4", "value4")

        # key1 should still exist (was accessed)
        self.assertEqual(self.cache.get("key1"), "value1")

        # key2 should be evicted (oldest access)
        self.assertIsNone(self.cache.get("key2"))

    def test_cache_invalidate_single(self):
        """Test invalidating single cache entry."""
        self.cache.set("key1", "value1")
        self.cache.set("key2", "value2")

        self.cache.invalidate("key1")

        self.assertIsNone(self.cache.get("key1"))
        self.assertEqual(self.cache.get("key2"), "value2")

    def test_cache_invalidate_all(self):
        """Test clearing entire cache."""
        self.cache.set("key1", "value1")
        self.cache.set("key2", "value2")

        self.cache.invalidate()

        self.assertIsNone(self.cache.get("key1"))
        self.assertIsNone(self.cache.get("key2"))

    def test_cache_stats(self):
        """Test cache statistics."""
        self.cache.set("key1", "value1")
        self.cache.set("key2", "value2")

        stats = self.cache.get_stats()

        self.assertEqual(stats["size"], 2)
        self.assertEqual(stats["max_size"], 3)
        self.assertAlmostEqual(stats["ttl_hours"], 0.001, places=3)
